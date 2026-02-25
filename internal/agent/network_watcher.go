// Package agent contains the TripWire agent orchestrator and its watcher
// components.
package agent

import (
	"bufio"
	"context"
	"encoding/hex"
	"fmt"
	"io"
	"log/slog"
	"net"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/tripwire/agent/internal/config"
)

// TCP connection state values from /proc/net/tcp.
const (
	tcpEstablished = 1
	tcpListen      = 10
)

// proc filesystem paths for connection tables.
const (
	procNetTCP = "/proc/net/tcp"
	procNetUDP = "/proc/net/udp"
)

// ConnEntry represents a single row in a /proc/net/tcp or /proc/net/udp file.
type ConnEntry struct {
	// LocalAddr is the local IP address in dotted-decimal form.
	LocalAddr string
	// LocalPort is the local port number.
	LocalPort int
	// RemoteAddr is the remote IP address in dotted-decimal form.
	RemoteAddr string
	// RemotePort is the remote port number.
	RemotePort int
	// State is the raw connection state value (e.g. 1 = ESTABLISHED, 10 = LISTEN).
	State int
}

// key returns a unique string identifier for this connection, used for
// de-duplicating alerts within a single poll cycle.
func (c ConnEntry) key() string {
	return fmt.Sprintf("%s:%d-%s:%d", c.LocalAddr, c.LocalPort, c.RemoteAddr, c.RemotePort)
}

// ProcNetReader reads network connection tables from the operating system.
// The default implementation reads from the real /proc/net/tcp and
// /proc/net/udp files. Alternative implementations can be injected in tests
// via WithProcNetReader to supply synthetic connection data without requiring
// elevated OS privileges.
type ProcNetReader interface {
	// ReadTCP returns all current TCP connections.
	ReadTCP() ([]ConnEntry, error)
	// ReadUDP returns all current UDP connections.
	ReadUDP() ([]ConnEntry, error)
}

// defaultProcNetReader reads from the real /proc/net/tcp and /proc/net/udp.
type defaultProcNetReader struct{}

func (r *defaultProcNetReader) ReadTCP() ([]ConnEntry, error) {
	return readProcNetFile(procNetTCP)
}

func (r *defaultProcNetReader) ReadUDP() ([]ConnEntry, error) {
	return readProcNetFile(procNetUDP)
}

// parsedNetworkRule is an internal representation of a NETWORK TripwireRule
// with the port pre-parsed to an integer.
type parsedNetworkRule struct {
	name     string
	port     int
	severity string
}

// NetworkWatcher monitors /proc/net/tcp and /proc/net/udp for new inbound TCP
// connections on configured ports. It implements the Watcher interface and can
// be registered with the Agent orchestrator via WithWatchers.
//
// On each poll it reads the current connection table, identifies connections to
// monitored ports that were not present in the previous poll, and emits an
// AlertEvent for each new connection. Connections that close between polls are
// removed from the tracking set, so that a reconnection from the same source
// generates a fresh alert.
//
// The default poll interval is 1 second.  The underlying connection reader is
// swappable via WithProcNetReader for unit testing without OS privileges.
type NetworkWatcher struct {
	rules        []parsedNetworkRule
	reader       ProcNetReader
	pollInterval time.Duration
	logger       *slog.Logger

	events    chan AlertEvent
	stopCh    chan struct{}
	stopOnce  sync.Once
	closeOnce sync.Once
	wg        sync.WaitGroup

	// activeConns tracks rule+connection keys seen in the previous poll.
	// It is only accessed from the single polling goroutine, so no mutex
	// is required.
	activeConns map[string]struct{}
}

// NetworkWatcherOption is a functional option for NewNetworkWatcher.
type NetworkWatcherOption func(*NetworkWatcher)

// WithPollInterval overrides the default 1-second poll interval.
func WithPollInterval(d time.Duration) NetworkWatcherOption {
	return func(w *NetworkWatcher) {
		w.pollInterval = d
	}
}

// WithProcNetReader replaces the real /proc/net reader with r.  Intended for
// tests: pass a fake reader that returns synthetic ConnEntry slices.
func WithProcNetReader(r ProcNetReader) NetworkWatcherOption {
	return func(w *NetworkWatcher) {
		w.reader = r
	}
}

// NewNetworkWatcher constructs a NetworkWatcher from a slice of TripwireRules.
// Only rules with Type == "NETWORK" are used; all others are silently skipped.
// The Target field of each NETWORK rule must be a decimal port number in the
// range 1–65535; rules that fail this validation are skipped with a warning.
func NewNetworkWatcher(rules []config.TripwireRule, logger *slog.Logger, opts ...NetworkWatcherOption) *NetworkWatcher {
	w := &NetworkWatcher{
		reader:       &defaultProcNetReader{},
		pollInterval: time.Second,
		logger:       logger,
		events:       make(chan AlertEvent, 64),
		stopCh:       make(chan struct{}),
		activeConns:  make(map[string]struct{}),
	}
	for _, opt := range opts {
		opt(w)
	}

	for _, r := range rules {
		if r.Type != "NETWORK" {
			continue
		}
		port, err := strconv.Atoi(r.Target)
		if err != nil || port < 1 || port > 65535 {
			logger.Warn("network watcher: invalid port target in rule, skipping",
				slog.String("rule", r.Name),
				slog.String("target", r.Target),
			)
			continue
		}
		w.rules = append(w.rules, parsedNetworkRule{
			name:     r.Name,
			port:     port,
			severity: r.Severity,
		})
	}

	return w
}

// Start begins polling the connection tables at the configured interval.
// It is non-blocking; all monitoring happens in a background goroutine.
// Events are delivered on the channel returned by Events.
// Start returns nil even when no NETWORK rules are configured; in that case
// the background goroutine runs but never emits any events.
func (w *NetworkWatcher) Start(_ context.Context) error {
	if len(w.rules) == 0 {
		w.logger.Warn("network watcher: no NETWORK rules configured, watcher will produce no events")
	}
	w.wg.Add(1)
	go func() {
		defer w.wg.Done()
		w.run()
	}()
	return nil
}

// Stop signals the background goroutine to exit and blocks until it has.
// The events channel is closed exactly once after all goroutines exit.
// Stop is safe to call multiple times.
func (w *NetworkWatcher) Stop() {
	w.stopOnce.Do(func() {
		close(w.stopCh)
	})
	w.wg.Wait()
	w.closeOnce.Do(func() {
		close(w.events)
	})
}

// Events returns the read-only channel on which AlertEvents are delivered.
func (w *NetworkWatcher) Events() <-chan AlertEvent {
	return w.events
}

// run is the main poll loop. It ticks at pollInterval until stopCh is closed.
func (w *NetworkWatcher) run() {
	ticker := time.NewTicker(w.pollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-w.stopCh:
			return
		case <-ticker.C:
			w.poll()
		}
	}
}

// poll reads the current TCP/UDP connection tables and emits events for any
// rule-matching connections that were not present in the previous poll.
func (w *NetworkWatcher) poll() {
	if len(w.rules) == 0 {
		return
	}

	tcpEntries, err := w.reader.ReadTCP()
	if err != nil {
		w.logger.Warn("network watcher: error reading TCP connections", slog.Any("error", err))
	}

	// Build the complete set of rule+connection keys visible in this poll.
	currentConns := make(map[string]struct{})

	for _, rule := range w.rules {
		for _, conn := range tcpEntries {
			// Only alert on established connections inbound to the monitored port.
			if conn.State != tcpEstablished {
				continue
			}
			if conn.LocalPort != rule.port {
				continue
			}

			k := rule.name + ":" + conn.key()
			currentConns[k] = struct{}{}

			if _, seen := w.activeConns[k]; seen {
				continue // already alerted in a previous poll
			}

			// New connection – emit an alert.
			w.emit(conn, rule)
		}
	}

	// Replace the active set so that closed connections are no longer tracked.
	// If a source reconnects, a fresh alert is generated.
	w.activeConns = currentConns
}

// emit sends an AlertEvent for conn matching rule onto the events channel.
// If the channel is full the event is dropped and a warning is logged.
func (w *NetworkWatcher) emit(conn ConnEntry, rule parsedNetworkRule) {
	evt := AlertEvent{
		TripwireType: "NETWORK",
		RuleName:     rule.name,
		Severity:     rule.severity,
		Timestamp:    time.Now().UTC(),
		Detail: map[string]any{
			"source_ip":   conn.RemoteAddr,
			"source_port": conn.RemotePort,
			"dest_port":   conn.LocalPort,
			"protocol":    "tcp",
			"direction":   "inbound",
		},
	}

	select {
	case w.events <- evt:
	default:
		w.logger.Warn("network watcher: events channel full, dropping alert",
			slog.String("rule", rule.name),
		)
	}
}

// ---------------------------------------------------------------------------
// /proc/net/tcp parser
// ---------------------------------------------------------------------------

// readProcNetFile opens path and delegates to ParseProcNet.
func readProcNetFile(path string) ([]ConnEntry, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("network watcher: open %s: %w", path, err)
	}
	defer f.Close()
	return ParseProcNet(f)
}

// ParseProcNet reads the /proc/net/tcp (or /proc/net/udp) format from r and
// returns all connection entries.  The header line is skipped automatically.
// It is exported so that tests can verify the parsing logic directly using
// synthetic /proc/net/tcp content without touching the filesystem.
//
// Each data line has the form:
//
//	sl  local_address rem_address   st ...
//	 0: 0100007F:0035 00000000:0000 0A ...
//
// Addresses are hexadecimal little-endian IPv4 (or big-endian for each 32-bit
// word of IPv6), and ports are big-endian hex.
func ParseProcNet(r io.Reader) ([]ConnEntry, error) {
	scanner := bufio.NewScanner(r)

	// Skip the header line.
	if !scanner.Scan() {
		return nil, scanner.Err()
	}

	var entries []ConnEntry
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		fields := strings.Fields(line)
		if len(fields) < 4 {
			continue
		}

		localAddr, localPort, err := parseHexAddr(fields[1])
		if err != nil {
			continue
		}
		remoteAddr, remotePort, err := parseHexAddr(fields[2])
		if err != nil {
			continue
		}
		state, err := strconv.ParseInt(fields[3], 16, 32)
		if err != nil {
			continue
		}

		entries = append(entries, ConnEntry{
			LocalAddr:  localAddr,
			LocalPort:  localPort,
			RemoteAddr: remoteAddr,
			RemotePort: remotePort,
			State:      int(state),
		})
	}

	return entries, scanner.Err()
}

// parseHexAddr parses a "AABBCCDD:PPPP" hex address from /proc/net/tcp into
// a dotted-decimal IP string and an integer port number.
//
// IPv4 addresses are stored in little-endian byte order (LSB first), so the
// bytes must be reversed to produce a human-readable address.
func parseHexAddr(s string) (ip string, port int, err error) {
	idx := strings.LastIndex(s, ":")
	if idx < 0 {
		return "", 0, fmt.Errorf("invalid address %q: missing colon", s)
	}
	ipHex := s[:idx]
	portHex := s[idx+1:]

	ipBytes, err := hex.DecodeString(ipHex)
	if err != nil {
		return "", 0, fmt.Errorf("invalid IP hex %q: %w", ipHex, err)
	}

	var ipAddr net.IP
	switch len(ipBytes) {
	case 4:
		// IPv4: bytes stored LSB-first; reverse to get network order.
		ipAddr = net.IP{ipBytes[3], ipBytes[2], ipBytes[1], ipBytes[0]}
	case 16:
		// IPv6: four 32-bit words, each stored LSB-first.
		rev := make([]byte, 16)
		for i := 0; i < 4; i++ {
			rev[i*4+0] = ipBytes[i*4+3]
			rev[i*4+1] = ipBytes[i*4+2]
			rev[i*4+2] = ipBytes[i*4+1]
			rev[i*4+3] = ipBytes[i*4+0]
		}
		ipAddr = net.IP(rev)
	default:
		return "", 0, fmt.Errorf("unexpected IP byte length %d for %q", len(ipBytes), ipHex)
	}

	p, err := strconv.ParseInt(portHex, 16, 32)
	if err != nil {
		return "", 0, fmt.Errorf("invalid port hex %q: %w", portHex, err)
	}

	return ipAddr.String(), int(p), nil
}
