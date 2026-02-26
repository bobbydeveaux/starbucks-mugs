package websocket_test

import (
	"bufio"
	"crypto/sha1" //nolint:gosec // SHA-1 mandated by RFC 6455
	"encoding/base64"
	"encoding/binary"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	ws "github.com/tripwire/agent/internal/server/websocket"
)

func newTestHandler() *ws.Handler {
	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError}))
	bc := ws.NewBroadcaster(logger, 16)
	return ws.NewHandler(bc, logger, time.Second)
}

// TestHandlerRejectsNonWebSocket verifies that a plain HTTP request returns
// 426 Upgrade Required.
func TestHandlerRejectsNonWebSocket(t *testing.T) {
	t.Parallel()

	h := newTestHandler()
	req := httptest.NewRequest(http.MethodGet, "/ws/alerts", nil)
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusUpgradeRequired {
		t.Errorf("expected status %d, got %d", http.StatusUpgradeRequired, rr.Code)
	}
}

// TestHandlerRejectsMissingKey verifies that a WebSocket upgrade request
// without Sec-WebSocket-Key returns 400 Bad Request.
func TestHandlerRejectsMissingKey(t *testing.T) {
	t.Parallel()

	h := newTestHandler()
	req := httptest.NewRequest(http.MethodGet, "/ws/alerts", nil)
	req.Header.Set("Upgrade", "websocket")
	req.Header.Set("Connection", "Upgrade")
	// No Sec-WebSocket-Key header.
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Errorf("expected status %d, got %d", http.StatusBadRequest, rr.Code)
	}
}

// TestHandlerWebSocketHandshake verifies that a valid WebSocket upgrade
// completes and that messages broadcast by the Broadcaster are received over
// the raw connection.
func TestHandlerWebSocketHandshake(t *testing.T) {
	t.Parallel()

	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError}))
	bc := ws.NewBroadcaster(logger, 16)
	handler := ws.NewHandler(bc, logger, 5*time.Second)

	srv := httptest.NewServer(handler)
	defer srv.Close()

	// Open a raw TCP connection to the test server and perform the WebSocket
	// handshake manually (avoids any external WebSocket client library).
	conn, err := net.Dial("tcp", strings.TrimPrefix(srv.URL, "http://"))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	// Send WebSocket upgrade request.
	clientKey := "dGhlIHNhbXBsZSBub25jZQ==" // standard test key from RFC 6455

	req := "GET /ws/alerts HTTP/1.1\r\n" +
		"Host: " + strings.TrimPrefix(srv.URL, "http://") + "\r\n" +
		"Upgrade: websocket\r\n" +
		"Connection: Upgrade\r\n" +
		"Sec-WebSocket-Key: " + clientKey + "\r\n" +
		"Sec-WebSocket-Version: 13\r\n" +
		"\r\n"

	if _, err := conn.Write([]byte(req)); err != nil {
		t.Fatalf("write upgrade request: %v", err)
	}

	// Read the HTTP response headers.
	reader := bufio.NewReader(conn)
	resp, err := http.ReadResponse(reader, nil)
	if err != nil {
		t.Fatalf("read response: %v", err)
	}
	if resp.StatusCode != http.StatusSwitchingProtocols {
		t.Fatalf("expected 101, got %d", resp.StatusCode)
	}

	// Verify the Sec-WebSocket-Accept header.
	expectedAccept := computeAcceptForTest(clientKey)
	gotAccept := resp.Header.Get("Sec-WebSocket-Accept")
	if gotAccept != expectedAccept {
		t.Errorf("Sec-WebSocket-Accept: got %q, want %q", gotAccept, expectedAccept)
	}

	// Give the server a moment to register the client.
	time.Sleep(50 * time.Millisecond)

	// Broadcast a message; it should arrive as a WebSocket text frame.
	bc.Broadcast(ws.AlertMessage{
		Type: "alert",
		Data: ws.AlertData{AlertID: "test-uuid", Severity: "INFO"},
	})

	// Read the WebSocket frame using the buffered reader (it may have already
	// buffered data from the HTTP response; reading from conn directly would
	// skip any buffered data).
	if err := conn.SetReadDeadline(time.Now().Add(500 * time.Millisecond)); err != nil {
		t.Fatalf("SetReadDeadline: %v", err)
	}

	// Read 2-byte frame header.
	b0, err := reader.ReadByte()
	if err != nil {
		t.Fatalf("read frame byte 0: %v", err)
	}
	b1, err := reader.ReadByte()
	if err != nil {
		t.Fatalf("read frame byte 1: %v", err)
	}

	if b0 != 0x81 {
		t.Errorf("expected FIN+text frame (0x81), got 0x%02x", b0)
	}
	if b1&0x80 != 0 {
		t.Fatal("server must not mask frames sent to clients (RFC 6455 §5.1)")
	}

	// Decode payload length.
	payloadLen := int(b1 & 0x7F)
	switch payloadLen {
	case 126:
		ext := make([]byte, 2)
		if _, err := reader.Read(ext); err != nil {
			t.Fatalf("read extended length: %v", err)
		}
		payloadLen = int(binary.BigEndian.Uint16(ext))
	case 127:
		ext := make([]byte, 8)
		if _, err := reader.Read(ext); err != nil {
			t.Fatalf("read extended length: %v", err)
		}
		payloadLen = int(binary.BigEndian.Uint64(ext))
	}

	payload := make([]byte, payloadLen)
	if _, err := reader.Read(payload); err != nil {
		t.Fatalf("read payload: %v", err)
	}

	if !strings.Contains(string(payload), "test-uuid") {
		t.Errorf("payload does not contain expected alert_id: %s", payload)
	}
}

// computeAcceptForTest replicates the server's Sec-WebSocket-Accept derivation.
func computeAcceptForTest(key string) string {
	const guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
	//nolint:gosec // SHA-1 mandated by RFC 6455
	h := sha1.New()
	h.Write([]byte(key + guid))
	return base64.StdEncoding.EncodeToString(h.Sum(nil))
}
