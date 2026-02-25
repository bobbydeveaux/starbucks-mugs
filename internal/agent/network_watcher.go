// Package agent contains the TripWire agent orchestrator and watcher components.
package agent

import (
	"bufio"
	"context"
	"encoding/hex"
	"fmt"
	"log/slog"
	"net"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/tripwire/agent/internal/config"
)

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

// ConnKey uniquely identifies an active network connection.  It is exported so
// that callers can construct connection snapshots for the injectable ProcReader.
type ConnKey struct {
	LocalAddr  string
	RemoteAddr string
	Protocol   string
}

// ProcReader is the type of a function that returns the current snapshot of
// established network connections.  The production implementation reads
// /proc/net/tcp*; tests may inject a stub via NewNetworkWatcherWithReader.
type ProcReader func() (map[ConnKey]struct{}, error)

// ---------------------------------------------------------------------------
// Internal types
// ---------------------------------------------------------------------------

// networkRule is a compiled NETWORK-type tripwire rule.
type networkRule struct {
	name     string
	port     int
	severity string
}

// ---------------------------------------------------------------------------
// NetworkWatcher
// ---------------------------------------------------------------------------

// NetworkWatcher monitors TCP connections on configured ports by periodically
// polling /proc/net/tcp and /proc/net/tcp6.  It implements the Watcher
// interface and is safe for concurrent use.
//
// A new AlertEvent is emitted each time a TCP ESTABLISHED connection is
// detected on a monitored local port that was not present in the previous poll.
type NetworkWatcher struct {
	rules        []networkRule
	pollInterval time.Duration
	logger       *slog.Logger
	reader       ProcReader

	events chan AlertEvent

	stopOnce sync.Once
	stopCh   chan struct{}
	done     chan struct{}

	mu   sync.Mutex
	seen map[ConnKey]struct{}
}

// NewNetworkWatcher creates a NetworkWatcher from the NETWORK-type rules in
// rules.  Non-NETWORK rules are silently ignored.
//
// pollInterval controls how often /proc/net/tcp* is re-read; values <= 0
// default to 1 second.
//
// An error is returned if any NETWORK rule has an invalid port target.
func NewNetworkWatcher(rules []config.TripwireRule, logger *slog.Logger, pollInterval time.Duration) (*NetworkWatcher, error) {
	return NewNetworkWatcherWithReader(rules, logger, pollInterval, nil)
}

// NewNetworkWatcherWithReader is identical to NewNetworkWatcher but accepts a
// custom ProcReader, enabling unit tests to inject connection snapshots without
// reading /proc/net/tcp*.  Passing nil for reader falls back to the default
// /proc-based implementation.
func NewNetworkWatcherWithReader(rules []config.TripwireRule, logger *slog.Logger, pollInterval time.Duration, reader ProcReader) (*NetworkWatcher, error) {
	if pollInterval <= 0 {
		pollInterval = time.Second
	}

	var compiled []networkRule
	for _, r := range rules {
		if r.Type != "NETWORK" {
			continue
		}
		port, err := strconv.Atoi(strings.TrimSpace(r.Target))
		if err != nil || port < 1 || port > 65535 {
			return nil, fmt.Errorf("network watcher: rule %q has invalid port target %q: must be an integer in [1, 65535]", r.Name, r.Target)
		}
		compiled = append(compiled, networkRule{
			name:     r.Name,
			port:     port,
			severity: r.Severity,
		})
	}

	if reader == nil {
		reader = defaultProcReader
	}

	return &NetworkWatcher{
		rules:        compiled,
		pollInterval: pollInterval,
		logger:       logger,
		reader:       reader,
		events:       make(chan AlertEvent, 64),
		stopCh:       make(chan struct{}),
		done:         make(chan struct{}),
		seen:         make(map[ConnKey]struct{}),
	}, nil
}

// Start begins polling /proc/net/tcp* for new connections on monitored ports.
// Monitoring continues until Stop is called or ctx is cancelled.
// Start must be called before Stop.
func (w *NetworkWatcher) Start(ctx context.Context) error {
	go w.run(ctx)
	return nil
}

// Stop signals the polling goroutine to stop and blocks until it has exited.
// The Events channel is closed after Stop returns.  It is safe to call Stop
// multiple times.
func (w *NetworkWatcher) Stop() {
	w.stopOnce.Do(func() {
		close(w.stopCh)
	})
	<-w.done
}

// Events returns a read-only channel from which callers receive AlertEvents.
// The channel is closed when the watcher exits (after Stop is called).
func (w *NetworkWatcher) Events() <-chan AlertEvent {
	return w.events
}

// ---------------------------------------------------------------------------
// Internal goroutine
// ---------------------------------------------------------------------------

// run is the main event loop.  It ticks every pollInterval, reads the current
// connection snapshot via the injected reader, and emits events for newly
// observed connections on monitored ports.
func (w *NetworkWatcher) run(ctx context.Context) {
	defer close(w.done)
	defer close(w.events)

	if len(w.rules) == 0 {
		w.logger.Debug("network watcher: no rules configured; exiting immediately")
		return
	}

	w.logger.Info("network watcher started",
		slog.Int("num_rules", len(w.rules)),
		slog.Duration("poll_interval", w.pollInterval),
	)

	ticker := time.NewTicker(w.pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			w.logger.Info("network watcher stopped (context cancelled)")
			return
		case <-w.stopCh:
			w.logger.Info("network watcher stopped")
			return
		case <-ticker.C:
			w.poll()
		}
	}
}

// poll reads the current connection snapshot and emits events for connections
// that are new since the last poll.
func (w *NetworkWatcher) poll() {
	current, err := w.reader()
	if err != nil {
		w.logger.Warn("network watcher: error reading connection state",
			slog.Any("error", err))
		return
	}

	w.mu.Lock()
	prev := w.seen
	w.seen = current
	w.mu.Unlock()

	for ck := range current {
		if _, alreadySeen := prev[ck]; alreadySeen {
			continue
		}
		w.matchAndEmit(ck)
	}
}

// matchAndEmit checks whether ck matches any configured rule and sends an
// AlertEvent if so.
func (w *NetworkWatcher) matchAndEmit(ck ConnKey) {
	port := portFromAddr(ck.LocalAddr)
	for _, r := range w.rules {
		if r.port != port {
			continue
		}
		evt := AlertEvent{
			TripwireType: "NETWORK",
			RuleName:     r.name,
			Severity:     r.severity,
			Timestamp:    time.Now().UTC(),
			Detail: map[string]any{
				"local_addr":  ck.LocalAddr,
				"remote_addr": ck.RemoteAddr,
				"protocol":    ck.Protocol,
			},
		}
		w.logger.Info("network tripwire triggered",
			slog.String("rule", r.name),
			slog.String("local", ck.LocalAddr),
			slog.String("remote", ck.RemoteAddr),
			slog.String("protocol", ck.Protocol),
		)
		select {
		case w.events <- evt:
		default:
			w.logger.Warn("network watcher: event channel full, dropping alert",
				slog.String("rule", r.name))
		}
	}
}

// ---------------------------------------------------------------------------
// /proc/net reader
// ---------------------------------------------------------------------------

// defaultProcReader reads /proc/net/tcp and /proc/net/tcp6 to collect
// currently ESTABLISHED TCP connections.  Missing files (e.g. tcp6 on kernels
// without IPv6 support) are skipped silently.
func defaultProcReader() (map[ConnKey]struct{}, error) {
	conns := make(map[ConnKey]struct{})

	for _, entry := range []struct {
		path  string
		proto string
	}{
		{"/proc/net/tcp", "tcp"},
		{"/proc/net/tcp6", "tcp6"},
	} {
		parsed, err := parseProcNetFile(entry.path, entry.proto)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return conns, fmt.Errorf("network watcher: reading %s: %w", entry.path, err)
		}
		for _, ck := range parsed {
			conns[ConnKey{
				LocalAddr:  ck.LocalAddr,
				RemoteAddr: ck.RemoteAddr,
				Protocol:   ck.Protocol,
			}] = struct{}{}
		}
	}
	return conns, nil
}

// ConnEntry holds a single decoded connection from a /proc/net file.
// It is returned by ParseProcNetFile and used internally by defaultProcReader.
type ConnEntry struct {
	LocalAddr  string
	RemoteAddr string
	Protocol   string
}

// ParseProcNetFile parses a /proc/net/tcp or /proc/net/tcp6 file and returns
// ESTABLISHED connections (socket state 0x01).  It is exported to allow
// testing the parsing logic with synthetic /proc/net data.
//
// The /proc/net/tcp format (space-separated columns):
//
//	sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode
//
// Addresses are hex-encoded: "XXXXXXXX:PPPP" for IPv4 (little-endian 4 bytes)
// or "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX:PPPP" for IPv6 (little-endian 4×32-bit).
func ParseProcNetFile(path, proto string) ([]ConnEntry, error) {
	return parseProcNetFile(path, proto)
}

func parseProcNetFile(path, proto string) ([]ConnEntry, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	var conns []ConnEntry
	scanner := bufio.NewScanner(f)
	lineNum := 0

	for scanner.Scan() {
		lineNum++
		if lineNum == 1 {
			continue // skip header line
		}

		fields := strings.Fields(scanner.Text())
		if len(fields) < 4 {
			continue
		}

		// fields[3] is the socket state as a hex byte.
		state, err := strconv.ParseUint(fields[3], 16, 8)
		if err != nil {
			continue
		}

		// 0x01 = TCP_ESTABLISHED.  Only track established connections.
		if state != 0x01 {
			continue
		}

		// Skip entries with an all-zero remote address (unconnected sockets).
		if isZeroHexAddr(fields[2]) {
			continue
		}

		localAddr, err := HexToAddr(fields[1])
		if err != nil {
			continue
		}
		remoteAddr, err := HexToAddr(fields[2])
		if err != nil {
			continue
		}

		conns = append(conns, ConnEntry{
			LocalAddr:  localAddr,
			RemoteAddr: remoteAddr,
			Protocol:   proto,
		})
	}

	return conns, scanner.Err()
}

// isZeroHexAddr reports whether a /proc/net hex address represents the zero
// address (all hex digits and colons are '0' or ':').
func isZeroHexAddr(hexAddr string) bool {
	for _, c := range hexAddr {
		if c != '0' && c != ':' {
			return false
		}
	}
	return true
}

// HexToAddr decodes a /proc/net hex-encoded address ("XXXXXXXX:PPPP" for IPv4
// or "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX:PPPP" for IPv6) into a human-readable
// "ip:port" string.  It is exported to allow testing the address decoder.
//
// Linux stores address bytes in little-endian order within each 32-bit word,
// so the bytes must be reversed before constructing the IP address.
func HexToAddr(hexAddr string) (string, error) {
	colon := strings.IndexByte(hexAddr, ':')
	if colon < 0 {
		return "", fmt.Errorf("hexToAddr: no colon in %q", hexAddr)
	}
	hexIP := hexAddr[:colon]
	hexPort := hexAddr[colon+1:]

	portNum, err := strconv.ParseUint(hexPort, 16, 16)
	if err != nil {
		return "", fmt.Errorf("hexToAddr: parsing port %q: %w", hexPort, err)
	}

	var ipStr string
	switch len(hexIP) {
	case 8: // IPv4: 4 bytes, little-endian
		b, err := hex.DecodeString(hexIP)
		if err != nil {
			return "", fmt.Errorf("hexToAddr: decoding IPv4 %q: %w", hexIP, err)
		}
		// Reverse byte order (little-endian → big-endian).
		ipStr = net.IPv4(b[3], b[2], b[1], b[0]).String()

	case 32: // IPv6: four little-endian 32-bit words
		b, err := hex.DecodeString(hexIP)
		if err != nil {
			return "", fmt.Errorf("hexToAddr: decoding IPv6 %q: %w", hexIP, err)
		}
		// Reverse each 4-byte word independently.
		reordered := make([]byte, 16)
		for i := 0; i < 4; i++ {
			reordered[i*4+0] = b[i*4+3]
			reordered[i*4+1] = b[i*4+2]
			reordered[i*4+2] = b[i*4+1]
			reordered[i*4+3] = b[i*4+0]
		}
		ipStr = net.IP(reordered).String()

	default:
		return "", fmt.Errorf("hexToAddr: unexpected IP hex length %d in %q", len(hexIP), hexAddr)
	}

	return net.JoinHostPort(ipStr, strconv.FormatUint(portNum, 10)), nil
}

// portFromAddr extracts the numeric port from a "host:port" string.
// Returns 0 on any parse error.
func portFromAddr(addr string) int {
	_, portStr, err := net.SplitHostPort(addr)
	if err != nil {
		return 0
	}
	port, err := strconv.Atoi(portStr)
	if err != nil {
		return 0
	}
	return port
}
