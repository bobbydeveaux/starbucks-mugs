// Linux implementation of ProcessWatcher using the NETLINK_CONNECTOR process
// connector. This mechanism delivers PROC_EVENT_EXEC notifications from the
// kernel with zero polling overhead — semantically equivalent to the eBPF
// tracepoint program in bpf/execve.c but without requiring a BPF compiler at
// build time.
//
// Privilege requirement: opening a NETLINK_CONNECTOR socket and subscribing
// to process events requires CAP_NET_ADMIN (or uid 0).
//
//go:build linux

package watcher

import (
	"context"
	"encoding/binary"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"syscall"
)

// ─── Netlink Connector kernel ABI constants ──────────────────────────────────
// Values from <linux/netlink.h> and <linux/connector.h>.  Never change.

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

// ─── Start ───────────────────────────────────────────────────────────────────

// Start opens a NETLINK_CONNECTOR socket, subscribes to kernel process events,
// and begins delivering AlertEvents for execve calls that match any configured
// PROCESS rule. It returns immediately after launching the background loop.
//
// The caller must hold CAP_NET_ADMIN or be uid 0; otherwise Start returns a
// descriptive error.
//
// Calling Start on an already-running watcher is a no-op (returns nil).
func (w *ProcessWatcher) Start(ctx context.Context) error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.cancel != nil {
		return nil // already running
	}

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

	ctx, cancel := context.WithCancel(ctx)
	w.cancel = cancel

	w.wg.Add(1)
	go w.readLoop(ctx, sock)

	w.logger.Info("process watcher started",
		slog.Int("rules", len(w.rules)),
		slog.String("mechanism", "NETLINK_CONNECTOR/PROC_EVENT_EXEC"),
	)
	return nil
}

// ─── Stop ────────────────────────────────────────────────────────────────────

// Stop signals the watcher to cease monitoring, waits for the background loop
// to exit, and closes the Events channel. Stop is safe to call multiple times
// (idempotent).
func (w *ProcessWatcher) Stop() {
	w.stopOnce.Do(func() {
		w.mu.Lock()
		cancel := w.cancel
		w.cancel = nil
		w.mu.Unlock()

		if cancel != nil {
			cancel()
		}
		w.wg.Wait()

		close(w.events)
		w.logger.Info("process watcher stopped")
	})
}

// ─── Background loop ─────────────────────────────────────────────────────────

// readLoop runs in a goroutine started by Start. It reads netlink messages
// from sock and dispatches PROC_EVENT_EXEC events. It exits when ctx is
// cancelled, after which it unsubscribes and closes the socket.
func (w *ProcessWatcher) readLoop(ctx context.Context, sock int) {
	defer w.wg.Done()
	defer func() { _ = syscall.Close(sock) }()

	// Set a per-read timeout so we can check ctx.Done() periodically without
	// blocking indefinitely in Recvfrom.
	tv := syscall.Timeval{Sec: 1, Usec: 0}
	_ = syscall.SetsockoptTimeval(sock, syscall.SOL_SOCKET, syscall.SO_RCVTIMEO, &tv)

	// Buffer large enough for several proc_event messages.
	buf := make([]byte, 8*1024)

	for {
		// Check for shutdown before blocking.
		select {
		case <-ctx.Done():
			_ = sendProcCNMsg(sock, procCNMcastIgnore) // best-effort unsubscribe
			return
		default:
		}

		n, _, err := syscall.Recvfrom(sock, buf, 0)
		if err != nil {
			// EAGAIN / EWOULDBLOCK mean the 1-second read timeout expired;
			// loop back to check ctx.Done().
			if err == syscall.EAGAIN || err == syscall.EWOULDBLOCK || err == syscall.EINTR {
				continue
			}
			// On a genuine read error check whether we are shutting down.
			select {
			case <-ctx.Done():
				return
			default:
			}
			w.logger.Warn("process watcher: recvfrom error",
				slog.Any("error", err),
			)
			return
		}

		w.parseNetlinkMessages(buf[:n])
	}
}

// ─── Message parsing ─────────────────────────────────────────────────────────

// parseNetlinkMessages splits buf into individual netlink messages and handles
// each PROC_EVENT_EXEC event it contains.
func (w *ProcessWatcher) parseNetlinkMessages(buf []byte) {
	msgs, err := syscall.ParseNetlinkMessage(buf)
	if err != nil {
		w.logger.Warn("process watcher: parse netlink message",
			slog.Any("error", err),
		)
		return
	}

	for i := range msgs {
		w.handleNetlinkMessage(&msgs[i])
	}
}

// handleNetlinkMessage processes one netlink message. It extracts the cn_msg
// and proc_event payload, ignoring anything that is not a PROC_EVENT_EXEC
// addressed to CN_IDX_PROC / CN_VAL_PROC.
func (w *ProcessWatcher) handleNetlinkMessage(msg *syscall.NetlinkMessage) {
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
	comm, exe, cmdline := readProcInfo(pid)

	w.emitExecEvent(pid, comm, exe, cmdline)
}

// ─── /proc enrichment ────────────────────────────────────────────────────────

// readProcInfo reads the short comm name, resolved exe path, and space-joined
// cmdline from /proc/<pid>. Empty strings are returned for any field that
// cannot be read (e.g. the process has already exited).
func readProcInfo(pid int) (comm, exe, cmdline string) {
	if b, err := os.ReadFile(fmt.Sprintf("/proc/%d/comm", pid)); err == nil {
		comm = strings.TrimRight(string(b), "\n\r")
	}
	if link, err := os.Readlink(fmt.Sprintf("/proc/%d/exe", pid)); err == nil {
		exe = link
	}
	if b, err := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid)); err == nil {
		// Args are NUL-separated; replace with spaces for readability.
		cmdline = strings.TrimRight(
			strings.ReplaceAll(string(b), "\x00", " "),
			" ",
		)
	}
	return comm, exe, cmdline
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
	binary.NativeEndian.PutUint32(buf[0:4], uint32(totalSize))      // Len
	binary.NativeEndian.PutUint16(buf[4:6], syscall.NLMSG_DONE)     // Type
	binary.NativeEndian.PutUint16(buf[6:8], 0)                      // Flags
	binary.NativeEndian.PutUint32(buf[8:12], 0)                     // Seq
	binary.NativeEndian.PutUint32(buf[12:16], uint32(os.Getpid()))  // Pid

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
