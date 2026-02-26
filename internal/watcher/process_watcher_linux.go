// Linux implementation of ProcessWatcher using the NETLINK_CONNECTOR process
// connector. This mechanism delivers PROC_EVENT_EXEC notifications from the
// kernel with zero polling overhead — semantically equivalent to the eBPF
// tracepoint program in internal/watcher/ebpf/process.bpf.c but without
// requiring a BPF compiler at build time.
//
// Privilege requirement: opening a NETLINK_CONNECTOR socket and subscribing
// to process events requires CAP_NET_ADMIN (or uid 0). If the agent lacks
// these privileges, Start returns a descriptive error via the backendStarter
// interface before any background goroutine is launched.
//
//go:build linux

package watcher

import (
	"bufio"
	"context"
	"encoding/binary"
	"fmt"
	"log/slog"
	"os"
	"strconv"
	"strings"
	"syscall"
)

// ─── Netlink Connector kernel ABI constants ──────────────────────────────────
// Values from <linux/netlink.h> and <linux/connector.h>. Never change.

const (
	// netlinkConnector is the NETLINK_CONNECTOR protocol family (11).
	netlinkConnector = 11

	// cnIdxProc / cnValProc are the cb_id fields that identify the
	// process-events connector — CN_IDX_PROC and CN_VAL_PROC.
	cnIdxProc uint32 = 1
	cnValProc uint32 = 1

	// procCNMcastListen / procCNMcastIgnore are the PROC_CN_MCAST_* ops
	// sent to the kernel to start / stop receiving process events.
	procCNMcastListen uint32 = 1
	procCNMcastIgnore uint32 = 2

	// procEventExec is the PROC_EVENT_EXEC flag in struct proc_event.what.
	procEventExec uint32 = 0x00000002
)

// ─── Kernel struct sizes (byte offsets) ─────────────────────────────────────
// These match the C struct layouts documented in <linux/cn_proc.h>.
//
//	struct cn_msg         { idx(4) val(4) seq(4) ack(4) len(2) flags(2) }  → 20 B
//	struct proc_event hdr { what(4) cpu(4) timestamp_ns(8) }               → 16 B
//	struct exec_proc_event{ process_pid(4) process_tgid(4) }               →  8 B
const (
	cnMsgSize       = 20
	procEvtHdrSize  = 16
	execInfoSize    = 8
	nlMsgHdrSize    = 16 // matches syscall.SizeofNlMsghdr
	minProcEventLen = cnMsgSize + procEvtHdrSize + execInfoSize
)

// ─── Backend ─────────────────────────────────────────────────────────────────

// newProcessBackend returns a NETLINK_CONNECTOR-based process monitoring
// backend. The returned backend implements backendStarter; its start method
// opens and binds the socket, returning an error if insufficient privilege.
func newProcessBackend(logger *slog.Logger) processBackend {
	return &netlinkBackend{logger: logger}
}

// netlinkBackend implements processBackend (run) and backendStarter (start).
// It uses the Linux NETLINK_CONNECTOR process connector to receive
// PROC_EVENT_EXEC notifications from the kernel.
type netlinkBackend struct {
	logger *slog.Logger
	sock   int // set by start(), used and closed by run()
}

// start implements backendStarter. It opens and binds the NETLINK_CONNECTOR
// socket and subscribes to kernel process events. Returns an error if the
// caller lacks CAP_NET_ADMIN or root privilege.
//
// The opened socket is stored in b.sock for use by run().
func (b *netlinkBackend) start(_ context.Context) error {
	sock, err := syscall.Socket(syscall.AF_NETLINK, syscall.SOCK_DGRAM, netlinkConnector)
	if err != nil {
		return fmt.Errorf("process watcher: open NETLINK_CONNECTOR socket: %w "+
			"(requires CAP_NET_ADMIN)", err)
	}

	// Bind to our PID so the kernel knows where to deliver events.
	sa := &syscall.SockaddrNetlink{
		Family: syscall.AF_NETLINK,
		Pid:    uint32(os.Getpid()),
	}
	if err := syscall.Bind(sock, sa); err != nil {
		_ = syscall.Close(sock)
		return fmt.Errorf("process watcher: bind NETLINK_CONNECTOR: %w", err)
	}

	// Tell the kernel to start sending PROC_EVENT_EXEC notifications.
	if err := sendProcCNMsg(sock, procCNMcastListen); err != nil {
		_ = syscall.Close(sock)
		return fmt.Errorf("process watcher: subscribe to proc events: %w", err)
	}

	b.sock = sock
	b.logger.Info("process watcher: NETLINK_CONNECTOR socket ready")
	return nil
}

// run implements processBackend. It reads PROC_EVENT_EXEC netlink messages
// from the socket opened by start() and emits a ProcessEvent for each exec
// event that can be enriched from /proc. Runs until done is closed.
func (b *netlinkBackend) run(done <-chan struct{}, events chan<- ProcessEvent) error {
	defer func() { _ = syscall.Close(b.sock) }()

	// Set a per-read timeout so we can check done periodically without
	// blocking indefinitely in Recvfrom.
	tv := syscall.Timeval{Sec: 1, Usec: 0}
	_ = syscall.SetsockoptTimeval(b.sock, syscall.SOL_SOCKET, syscall.SO_RCVTIMEO, &tv)

	// Buffer large enough for several proc_event messages.
	buf := make([]byte, 8*1024)

	for {
		// Check for shutdown before blocking.
		select {
		case <-done:
			_ = sendProcCNMsg(b.sock, procCNMcastIgnore) // best-effort unsubscribe
			return nil
		default:
		}

		n, _, err := syscall.Recvfrom(b.sock, buf, 0)
		if err != nil {
			// EAGAIN / EWOULDBLOCK mean the 1-second read timeout expired;
			// loop back to check done.
			if err == syscall.EAGAIN || err == syscall.EWOULDBLOCK || err == syscall.EINTR {
				continue
			}
			// On a genuine read error check whether we are shutting down.
			select {
			case <-done:
				return nil
			default:
			}
			b.logger.Warn("process watcher: recvfrom error",
				slog.Any("error", err),
			)
			return err
		}

		b.parseNetlinkMessages(buf[:n], done, events)
	}
}

// ─── Message parsing ─────────────────────────────────────────────────────────

// parseNetlinkMessages splits buf into individual netlink messages and handles
// each PROC_EVENT_EXEC event it contains.
func (b *netlinkBackend) parseNetlinkMessages(buf []byte, done <-chan struct{}, events chan<- ProcessEvent) {
	msgs, err := syscall.ParseNetlinkMessage(buf)
	if err != nil {
		b.logger.Warn("process watcher: parse netlink message",
			slog.Any("error", err),
		)
		return
	}

	for i := range msgs {
		b.handleNetlinkMessage(&msgs[i], done, events)
	}
}

// handleNetlinkMessage processes one netlink message. It extracts the cn_msg
// and proc_event payload, ignoring anything that is not a PROC_EVENT_EXEC
// addressed to CN_IDX_PROC / CN_VAL_PROC.
func (b *netlinkBackend) handleNetlinkMessage(msg *syscall.NetlinkMessage, done <-chan struct{}, events chan<- ProcessEvent) {
	if msg.Header.Type == syscall.NLMSG_ERROR {
		return
	}

	data := msg.Data
	if len(data) < minProcEventLen {
		return
	}

	// Parse cn_msg header fields using native byte order (kernel ABI).
	idx := binary.NativeEndian.Uint32(data[0:4])
	val := binary.NativeEndian.Uint32(data[4:8])
	if idx != cnIdxProc || val != cnValProc {
		return // not a process-connector message
	}

	payloadLen := int(binary.NativeEndian.Uint16(data[16:18]))
	payload := data[cnMsgSize:]
	if payloadLen > len(payload) {
		return
	}
	payload = payload[:payloadLen]

	if len(payload) < procEvtHdrSize+execInfoSize {
		return
	}

	// proc_event.what
	what := binary.NativeEndian.Uint32(payload[0:4])
	if what != procEventExec {
		return // not an exec event (fork, exit, uid-change, etc.)
	}

	// exec_proc_event.process_pid follows the 16-byte proc_event header.
	pid := int(binary.NativeEndian.Uint32(payload[procEvtHdrSize : procEvtHdrSize+4]))

	// Enrich with data from /proc before the short-lived process can exit.
	pe, err := readProcEntry(pid)
	if err != nil {
		// Process already exited between the exec event and our /proc read;
		// silently skip rather than emitting an incomplete event.
		return
	}

	select {
	case events <- pe:
	case <-done:
	default:
		b.logger.Warn("process watcher: backend event channel full; dropping event",
			slog.Int("pid", pid),
			slog.String("command", pe.Command),
		)
	}
}

// ─── /proc enrichment ────────────────────────────────────────────────────────

// readProcEntry parses /proc/<pid>/status to extract the process name (Name),
// parent PID (PPid), and real UID (Uid). It also reads /proc/<pid>/cmdline for
// the full command line. Returns an error if the process has exited or the
// status file is unreadable.
func readProcEntry(pid int) (ProcessEvent, error) {
	statusPath := fmt.Sprintf("/proc/%d/status", pid)
	f, err := os.Open(statusPath)
	if err != nil {
		return ProcessEvent{}, err
	}
	defer f.Close()

	var pe ProcessEvent
	pe.PID = pid

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		switch {
		case strings.HasPrefix(line, "Name:\t"):
			pe.Command = strings.TrimPrefix(line, "Name:\t")
		case strings.HasPrefix(line, "PPid:\t"):
			pe.PPID, _ = strconv.Atoi(strings.TrimPrefix(line, "PPid:\t"))
		case strings.HasPrefix(line, "Uid:\t"):
			// Format: "Uid:\treal\teffective\tsaved\tfs"
			fields := strings.Fields(line)
			if len(fields) >= 2 {
				pe.UID, _ = strconv.Atoi(fields[1])
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return ProcessEvent{}, err
	}

	pe.Username = resolveUsername(pe.UID)

	// Read the full argv from /proc/<pid>/cmdline (NUL-separated args).
	// The file may be empty for kernel threads; that is not an error.
	cmdlinePath := fmt.Sprintf("/proc/%d/cmdline", pid)
	cmdlineBytes, err := os.ReadFile(cmdlinePath)
	if err == nil && len(cmdlineBytes) > 0 {
		// NUL separators between argv entries → replace with spaces and trim.
		pe.CmdLine = strings.TrimRight(
			strings.ReplaceAll(string(cmdlineBytes), "\x00", " "),
			" ",
		)
	}

	return pe, nil
}

// ─── Netlink send helper ─────────────────────────────────────────────────────

// sendProcCNMsg builds and sends a NETLINK_CONNECTOR message that instructs
// the kernel to start (PROC_CN_MCAST_LISTEN) or stop (PROC_CN_MCAST_IGNORE)
// delivering process events to the calling socket.
//
// Message layout:
//
//	nlmsghdr (16 B) + cn_msg (20 B) + uint32 op (4 B) = 40 B total
func sendProcCNMsg(sock int, op uint32) error {
	const opSize = 4
	const totalSize = nlMsgHdrSize + cnMsgSize + opSize
	buf := make([]byte, totalSize)

	// ── nlmsghdr ──────────────────────────────────────────────────────────
	binary.NativeEndian.PutUint32(buf[0:4], uint32(totalSize))     // Len
	binary.NativeEndian.PutUint16(buf[4:6], syscall.NLMSG_DONE)    // Type
	binary.NativeEndian.PutUint16(buf[6:8], 0)                     // Flags
	binary.NativeEndian.PutUint32(buf[8:12], 0)                    // Seq
	binary.NativeEndian.PutUint32(buf[12:16], uint32(os.Getpid())) // Pid

	// ── cn_msg ────────────────────────────────────────────────────────────
	off := nlMsgHdrSize
	binary.NativeEndian.PutUint32(buf[off+0:off+4], cnIdxProc) // idx
	binary.NativeEndian.PutUint32(buf[off+4:off+8], cnValProc) // val
	binary.NativeEndian.PutUint32(buf[off+8:off+12], 0)        // seq
	binary.NativeEndian.PutUint32(buf[off+12:off+16], 0)       // ack
	binary.NativeEndian.PutUint16(buf[off+16:off+18], opSize)  // len
	binary.NativeEndian.PutUint16(buf[off+18:off+20], 0)       // flags

	// ── op payload ────────────────────────────────────────────────────────
	off += cnMsgSize
	binary.NativeEndian.PutUint32(buf[off:off+4], op)

	// Deliver to the kernel (pid=0).
	dst := &syscall.SockaddrNetlink{Family: syscall.AF_NETLINK, Pid: 0}
	return syscall.Sendto(sock, buf, 0, dst)
}
