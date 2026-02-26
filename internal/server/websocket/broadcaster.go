// Package websocket provides the real-time alert fan-out layer for the
// TripWire dashboard server.
//
// The Broadcaster maintains a registry of connected WebSocket clients and
// publishes alert messages to all of them concurrently.  For single-instance
// deployments the broadcaster is in-process (backed by a sync.Map).  For
// multi-instance deployments, operators replace the broadcaster with a
// Redis-backed implementation that satisfies the same Publisher interface.
package websocket

import (
	"encoding/json"
	"log/slog"
	"sync"
	"sync/atomic"
)

// AlertMessage is the JSON envelope pushed to every connected browser client
// when a new alert arrives.  The structure matches the WebSocket protocol
// defined in the TripWire HLD.
type AlertMessage struct {
	Type string      `json:"type"` // always "alert"
	Data AlertData   `json:"data"`
}

// AlertData carries the alert fields visible to the browser.
type AlertData struct {
	AlertID      string          `json:"alert_id"`
	HostID       string          `json:"host_id"`
	Hostname     string          `json:"hostname"`
	Timestamp    string          `json:"timestamp"` // RFC 3339
	TripwireType string          `json:"tripwire_type"`
	RuleName     string          `json:"rule_name"`
	Severity     string          `json:"severity"`
	EventDetail  json.RawMessage `json:"event_detail,omitempty"`
}

// Client represents a single connected WebSocket browser session.
//
// Each client owns a buffered send channel.  The broadcaster writes to this
// channel without blocking; if the channel is full (slow consumer) the
// message is dropped and Dropped is incremented.
type Client struct {
	id      string
	send    chan []byte
	Dropped atomic.Int64
}

// newClient allocates a Client with the given unique id.
// bufSize controls how many messages can be queued before dropping occurs.
func newClient(id string, bufSize int) *Client {
	return &Client{
		id:   id,
		send: make(chan []byte, bufSize),
	}
}

// Send returns the receive-only channel that the WebSocket writer goroutine
// should drain.
func (c *Client) Send() <-chan []byte {
	return c.send
}

// ID returns the client's unique identifier.
func (c *Client) ID() string {
	return c.id
}

// Broadcaster fans out serialised alert messages to all registered Client
// instances.  It is safe for concurrent use from multiple goroutines.
type Broadcaster struct {
	clients sync.Map // map[string]*Client
	logger  *slog.Logger
	bufSize int
}

// NewBroadcaster creates a Broadcaster.
//
// clientBufSize is the per-client send-channel buffer depth.  A value of 64
// is reasonable for most deployments; increase if browser clients are slow
// consumers.
func NewBroadcaster(logger *slog.Logger, clientBufSize int) *Broadcaster {
	if clientBufSize <= 0 {
		clientBufSize = 64
	}
	return &Broadcaster{
		logger:  logger,
		bufSize: clientBufSize,
	}
}

// Register adds a new Client to the broadcaster and returns it.
//
// The caller is responsible for calling Unregister when the WebSocket
// connection closes.
func (b *Broadcaster) Register(id string) *Client {
	c := newClient(id, b.bufSize)
	b.clients.Store(id, c)
	b.logger.Debug("websocket client registered", slog.String("client_id", id))
	return c
}

// Unregister removes the client identified by id and closes its send channel
// so that the writer goroutine exits cleanly.
func (b *Broadcaster) Unregister(id string) {
	if v, ok := b.clients.LoadAndDelete(id); ok {
		c := v.(*Client)
		close(c.send)
		b.logger.Debug("websocket client unregistered", slog.String("client_id", id))
	}
}

// Broadcast serialises msg as JSON and delivers it to every registered
// client.  Clients with full send buffers are skipped and their Dropped
// counter is incremented.  Broadcast never blocks.
func (b *Broadcaster) Broadcast(msg AlertMessage) {
	raw, err := json.Marshal(msg)
	if err != nil {
		b.logger.Error("websocket: failed to marshal alert message", slog.Any("error", err))
		return
	}

	b.clients.Range(func(_, v any) bool {
		c := v.(*Client)
		select {
		case c.send <- raw:
		default:
			c.Dropped.Add(1)
			b.logger.Warn("websocket: client send buffer full, message dropped",
				slog.String("client_id", c.id))
		}
		return true
	})
}

// ClientCount returns the number of currently registered clients.
func (b *Broadcaster) ClientCount() int {
	count := 0
	b.clients.Range(func(_, _ any) bool {
		count++
		return true
	})
	return count
}
