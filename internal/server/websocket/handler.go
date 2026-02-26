package websocket

import (
	"bufio"
	"crypto/sha1" //nolint:gosec // SHA-1 is mandated by RFC 6455 §4.1; not used for security
	"encoding/base64"
	"encoding/binary"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"strings"
	"sync/atomic"
	"time"

	"github.com/google/uuid"
)

// maxFrameSize is the maximum WebSocket payload length (in bytes) that the
// server will accept from clients.  Frames exceeding this limit cause the
// read loop to drop the connection rather than allocating unbounded memory.
// Browser clients never send frames anywhere near this size; 64 KiB is a
// conservative guard against misbehaving or malicious clients.
const maxFrameSize = 64 * 1024 // 64 KiB

// wsGUID is the fixed GUID defined in RFC 6455 §4.1 for computing the
// Sec-WebSocket-Accept header value.
const wsGUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

// Handler is an http.Handler that upgrades HTTP connections to WebSocket and
// drives the per-client read/write loops.
//
// Incoming WebSocket connections are registered with the Broadcaster; the
// handler goroutine reads (and discards) any client-to-server frames (clients
// do not send alerts) and simultaneously writes broadcast messages from the
// Client.Send() channel as server-to-client text frames.
type Handler struct {
	bc     *Broadcaster
	logger *slog.Logger

	// writeTimeout is how long the handler waits for a write to complete
	// before closing the connection.
	writeTimeout time.Duration
}

// NewHandler creates a Handler backed by bc.
//
// writeTimeout ≤ 0 defaults to 10 seconds.
func NewHandler(bc *Broadcaster, logger *slog.Logger, writeTimeout time.Duration) *Handler {
	if writeTimeout <= 0 {
		writeTimeout = 10 * time.Second
	}
	return &Handler{
		bc:           bc,
		logger:       logger,
		writeTimeout: writeTimeout,
	}
}

// ServeHTTP handles the HTTP → WebSocket upgrade and drives the connection
// lifecycle.
func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// --- 1. Validate the upgrade request -----------------------------------------
	if !isWebSocketUpgrade(r) {
		http.Error(w, "websocket upgrade required", http.StatusUpgradeRequired)
		return
	}

	key := r.Header.Get("Sec-WebSocket-Key")
	if key == "" {
		http.Error(w, "missing Sec-WebSocket-Key", http.StatusBadRequest)
		return
	}

	// --- 2. Hijack the TCP connection so we can take over the framing ------------
	hj, ok := w.(http.Hijacker)
	if !ok {
		http.Error(w, "server does not support hijacking", http.StatusInternalServerError)
		return
	}

	conn, bufrw, err := hj.Hijack()
	if err != nil {
		h.logger.Error("websocket: hijack failed", slog.Any("error", err))
		return
	}

	// --- 3. Send the 101 Switching Protocols handshake response ------------------
	accept := computeAcceptKey(key)
	resp := "HTTP/1.1 101 Switching Protocols\r\n" +
		"Upgrade: websocket\r\n" +
		"Connection: Upgrade\r\n" +
		"Sec-WebSocket-Accept: " + accept + "\r\n\r\n"

	if _, err := bufrw.WriteString(resp); err != nil {
		h.logger.Error("websocket: handshake write failed", slog.Any("error", err))
		conn.Close()
		return
	}
	if err := bufrw.Flush(); err != nil {
		h.logger.Error("websocket: handshake flush failed", slog.Any("error", err))
		conn.Close()
		return
	}

	// --- 4. Register the client --------------------------------------------------
	clientID := uuid.NewString()
	client := h.bc.Register(clientID)
	defer h.bc.Unregister(clientID)

	h.logger.Info("websocket: client connected",
		slog.String("client_id", clientID),
		slog.String("remote_addr", conn.RemoteAddr().String()),
	)

	// closeConn is an atomic flag to prevent double-close when the reader or
	// writer goroutine exits first.
	var closed atomic.Bool

	closeOnce := func() {
		if closed.CompareAndSwap(false, true) {
			conn.Close()
		}
	}

	// --- 5. Start reader goroutine (discards client frames, detects close) -------
	done := make(chan struct{})
	go func() {
		defer close(done)
		defer func() {
			// Recover from any panic inside readLoop (e.g. a bug that slips
			// past the frame-size guard) so that a single bad client cannot
			// crash the entire server process.
			if r := recover(); r != nil {
				h.logger.Error("websocket: readLoop panic recovered",
					slog.Any("recover", r),
					slog.String("client_id", clientID),
				)
			}
		}()
		readLoop(conn, h.logger, clientID)
		closeOnce()
	}()

	// --- 6. Write loop — drain Client.Send() channel into WebSocket frames -------
	for {
		select {
		case <-done:
			return

		case msg, ok := <-client.Send():
			if !ok {
				// Broadcaster closed the channel — connection shutting down.
				closeOnce()
				return
			}

			if err := conn.SetWriteDeadline(time.Now().Add(h.writeTimeout)); err != nil {
				h.logger.Warn("websocket: set write deadline failed",
					slog.String("client_id", clientID), slog.Any("error", err))
				closeOnce()
				return
			}

			if err := writeTextFrame(conn, msg); err != nil {
				h.logger.Warn("websocket: write frame failed",
					slog.String("client_id", clientID), slog.Any("error", err))
				closeOnce()
				return
			}
		}
	}
}

// --- helpers -------------------------------------------------------------------

// isWebSocketUpgrade returns true when the request carries the WebSocket
// upgrade headers as specified in RFC 6455 §4.1.
func isWebSocketUpgrade(r *http.Request) bool {
	return strings.EqualFold(r.Header.Get("Upgrade"), "websocket") &&
		strings.Contains(strings.ToLower(r.Header.Get("Connection")), "upgrade")
}

// computeAcceptKey derives the Sec-WebSocket-Accept value from the client's
// Sec-WebSocket-Key as defined in RFC 6455 §4.1.
func computeAcceptKey(key string) string {
	//nolint:gosec // SHA-1 is mandated by RFC 6455; not used for security
	h := sha1.New()
	h.Write([]byte(key + wsGUID))
	return base64.StdEncoding.EncodeToString(h.Sum(nil))
}

// writeTextFrame encodes payload as a single, unfragmented WebSocket text
// frame (FIN=1, opcode=0x1) and writes it to conn.
//
// Server-to-client frames must NOT be masked (RFC 6455 §5.1).
func writeTextFrame(conn net.Conn, payload []byte) error {
	n := len(payload)
	var header []byte

	switch {
	case n < 126:
		header = []byte{0x81, byte(n)}
	case n < 65536:
		header = []byte{0x81, 126, 0, 0}
		binary.BigEndian.PutUint16(header[2:], uint16(n))
	default:
		header = make([]byte, 10)
		header[0] = 0x81
		header[1] = 127
		binary.BigEndian.PutUint64(header[2:], uint64(n))
	}

	if _, err := conn.Write(header); err != nil {
		return fmt.Errorf("write header: %w", err)
	}
	if _, err := conn.Write(payload); err != nil {
		return fmt.Errorf("write payload: %w", err)
	}
	return nil
}

// readLoop reads and discards incoming WebSocket frames from conn until the
// connection is closed or a close frame is received.  It exists to detect
// client disconnection and to prevent the receive buffer from filling up.
func readLoop(conn net.Conn, logger *slog.Logger, clientID string) {
	buf := bufio.NewReader(conn)
	for {
		// Read the 2-byte frame header.
		b0, err := buf.ReadByte()
		if err != nil {
			break
		}
		b1, err := buf.ReadByte()
		if err != nil {
			break
		}

		opcode := b0 & 0x0F
		masked := (b1 & 0x80) != 0
		length := int64(b1 & 0x7F)

		// Extended payload length.
		switch length {
		case 126:
			var ext [2]byte
			if _, err := buf.Read(ext[:]); err != nil {
				return
			}
			length = int64(binary.BigEndian.Uint16(ext[:]))
		case 127:
			var ext [8]byte
			if _, err := buf.Read(ext[:]); err != nil {
				return
			}
			// Guard against int64 overflow: binary.BigEndian.Uint64 returns a
			// uint64; values > math.MaxInt64 would wrap to a negative int64 and
			// cause make([]byte, length) to panic.  Reject any frame that
			// exceeds maxFrameSize — browser clients never send frames this large.
			rawLen := binary.BigEndian.Uint64(ext[:])
			if rawLen > maxFrameSize {
				return
			}
			length = int64(rawLen)
		}

		// Read and discard the 4-byte masking key if present.
		if masked {
			var maskKey [4]byte
			if _, err := buf.Read(maskKey[:]); err != nil {
				return
			}
		}

		// Discard the payload without allocating a full buffer; io.CopyN reads
		// in small chunks and prevents memory exhaustion from large frames.
		if length > 0 {
			if _, err := io.CopyN(io.Discard, buf, length); err != nil {
				return
			}
		}

		// Close frame (opcode 8) — graceful client disconnect.
		if opcode == 0x08 {
			logger.Debug("websocket: received close frame", slog.String("client_id", clientID))
			return
		}
	}
}
