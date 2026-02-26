// Package websocket provides the in-process WebSocket broadcaster for the
// TripWire dashboard server.  The Broadcaster fans newly ingested alerts out
// to all currently-connected browser clients without blocking the gRPC alert
// ingestion goroutine.
//
// Design notes
//
//   - Each WebSocket client has a dedicated buffered channel of JSON-encoded
//     alert messages.  A non-blocking send is used so that a slow or
//     disconnected client never applies back-pressure to the gRPC StreamAlerts
//     goroutine.
//   - Named clients are tracked in a sync.Map keyed by client ID to allow
//     concurrent reads without a global lock on the hot broadcast path.
//   - Anonymous subscribers (used by the integration layer) receive
//     storage.Alert values directly via a second sync.Map.
//   - Closing a subscription or unregistering a client signals the associated
//     WebSocket pump goroutine to exit cleanly.
package websocket

import (
	"context"
	"encoding/json"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"

	"github.com/tripwire/agent/internal/server/storage"
)

// AlertData holds the structured alert payload sent to browser clients as
// part of an AlertMessage envelope.
type AlertData struct {
	AlertID      string `json:"alert_id"`
	HostID       string `json:"host_id"`
	Hostname     string `json:"hostname"`
	Timestamp    string `json:"timestamp"`
	TripwireType string `json:"tripwire_type"`
	RuleName     string `json:"rule_name"`
	Severity     string `json:"severity"`
}

// AlertMessage is the top-level JSON envelope pushed to browser WebSocket
// clients.  Type is always "alert" for alert events.
type AlertMessage struct {
	Type string    `json:"type"`
	Data AlertData `json:"data"`
}

// Client represents a single connected WebSocket client.  It is created by
// Broadcaster.Register and is valid until Broadcaster.Unregister is called.
type Client struct {
	id      string
	send    chan []byte
	Dropped atomic.Int64 // incremented when the send buffer is full
}

// ID returns the client's unique identifier.
func (c *Client) ID() string { return c.id }

// Send returns a receive-only channel on which JSON-encoded alert frames are
// delivered.  The channel is closed when the client is unregistered.
func (c *Client) Send() <-chan []byte { return c.send }

// Broadcaster fans alert events out to all currently-connected WebSocket
// clients (via Register/Unregister/Broadcast) and to all anonymous channel
// subscribers (via Subscribe/Unsubscribe/Publish).  It is safe for concurrent
// use.
//
// For multi-instance dashboard deployments the same fan-out logic can be
// backed by a Redis pub/sub adapter without changing the alert service or
// WebSocket handler code.
type Broadcaster struct {
	// Named WebSocket clients — keyed by string client ID.
	clients   sync.Map    // map[string]*Client
	clientCnt atomic.Int64

	// Anonymous subscribers — keyed by the receive-only channel pointer.
	subs sync.Map // map[<-chan storage.Alert]chan storage.Alert

	bufSize int
	logger  *slog.Logger

	closed    atomic.Bool
	closeOnce sync.Once
}

// NewBroadcaster creates a Broadcaster.
//
// bufSize is the per-client and per-subscriber channel buffer depth.  A value
// of 64 is sufficient for a 100 ms flush interval generating up to 640
// alerts/s per subscriber before drops begin.  Pass 0 to use the default of
// 64.
func NewBroadcaster(logger *slog.Logger, bufSize int) *Broadcaster {
	if bufSize <= 0 {
		bufSize = 64
	}
	return &Broadcaster{
		bufSize: bufSize,
		logger:  logger,
	}
}

// Register creates a new Client with the given id, stores it in the
// broadcaster, and returns a pointer to it.  The caller must call
// Unregister(id) to release resources when the client disconnects.
//
// If the broadcaster is already closed, Register returns a Client whose Send
// channel is already closed.
func (b *Broadcaster) Register(id string) *Client {
	c := &Client{
		id:   id,
		send: make(chan []byte, b.bufSize),
	}
	if b.closed.Load() {
		close(c.send)
		return c
	}
	b.clients.Store(id, c)
	b.clientCnt.Add(1)
	return c
}

// Unregister removes the client with id from the broadcaster and closes its
// Send channel so the associated write goroutine exits cleanly.  Calling
// Unregister with an unknown id is a no-op.
func (b *Broadcaster) Unregister(id string) {
	if v, loaded := b.clients.LoadAndDelete(id); loaded {
		c := v.(*Client)
		close(c.send)
		b.clientCnt.Add(-1)
	}
}

// ClientCount returns the number of currently registered WebSocket clients.
func (b *Broadcaster) ClientCount() int {
	return int(b.clientCnt.Load())
}

// Broadcast marshals msg to JSON and delivers the payload to every registered
// client using a non-blocking send.  When a client's buffer is full the
// message is dropped and the client's Dropped counter is incremented.
func (b *Broadcaster) Broadcast(msg AlertMessage) {
	if b.closed.Load() {
		return
	}

	raw, err := json.Marshal(msg)
	if err != nil {
		b.logger.Error("websocket broadcaster: marshal failed", slog.Any("error", err))
		return
	}

	b.clients.Range(func(_, v any) bool {
		c := v.(*Client)
		select {
		case c.send <- raw:
			// delivered
		default:
			c.Dropped.Add(1)
			b.logger.Warn("websocket broadcaster: client buffer full, dropping alert",
				slog.String("client_id", c.id),
			)
		}
		return true // continue ranging
	})
}

// Subscribe registers an anonymous subscriber and returns a channel on which
// storage.Alert values will be delivered.  The channel is buffered; when the
// buffer is full a subsequent Publish call drops the alert for that subscriber
// rather than blocking.
//
// The channel is closed automatically when ctx is cancelled or when Close is
// called.  Call Unsubscribe to release resources before the context is
// cancelled.
func (b *Broadcaster) Subscribe(ctx context.Context) <-chan storage.Alert {
	ch := make(chan storage.Alert, b.bufSize)
	if b.closed.Load() {
		close(ch)
		return ch
	}
	b.subs.Store(ch, ch)

	// Unsubscribe automatically when the caller's context is cancelled.
	if ctx != nil {
		go func() {
			<-ctx.Done()
			b.Unsubscribe(ch)
		}()
	}

	return ch
}

// Unsubscribe removes the subscription associated with ch and closes the
// channel so the consumer loop exits cleanly.  It is safe to call Unsubscribe
// after the broadcaster has been closed.
func (b *Broadcaster) Unsubscribe(ch <-chan storage.Alert) {
	if actual, loaded := b.subs.LoadAndDelete(ch); loaded {
		close(actual.(chan storage.Alert))
	}
}

// Publish delivers a to every anonymous subscriber and also converts it to an
// AlertMessage that is broadcast to every registered WebSocket client.
//
// The non-blocking select/default pattern ensures that a slow subscriber or
// client never stalls the gRPC StreamAlerts goroutine.
func (b *Broadcaster) Publish(a storage.Alert) {
	if b.closed.Load() {
		return
	}

	// Deliver to Subscribe() subscribers as raw storage.Alert.
	b.subs.Range(func(key, value any) bool {
		ch := value.(chan storage.Alert)
		select {
		case ch <- a:
			// delivered
		default:
			b.logger.Warn("websocket broadcaster: subscriber buffer full, dropping alert",
				slog.String("alert_id", a.AlertID),
				slog.String("severity", string(a.Severity)),
			)
		}
		return true // continue ranging
	})

	// Convert to AlertMessage and fan out to registered WebSocket clients.
	b.Broadcast(AlertMessage{
		Type: "alert",
		Data: AlertData{
			AlertID:      a.AlertID,
			HostID:       a.HostID,
			Timestamp:    a.Timestamp.UTC().Format(time.RFC3339),
			TripwireType: string(a.TripwireType),
			RuleName:     a.RuleName,
			Severity:     string(a.Severity),
		},
	})
}

// Close removes all subscriptions and registered clients, drains and closes
// every channel, and releases internal resources.  After Close returns,
// Publish and Broadcast are no-ops and Subscribe returns a closed channel.
func (b *Broadcaster) Close() {
	b.closeOnce.Do(func() {
		b.closed.Store(true)

		// Close all anonymous subscriber channels.
		b.subs.Range(func(key, value any) bool {
			b.subs.Delete(key)
			close(value.(chan storage.Alert))
			return true
		})

		// Close all registered WebSocket client channels.
		b.clients.Range(func(key, value any) bool {
			b.clients.Delete(key)
			c := value.(*Client)
			close(c.send)
			b.clientCnt.Add(-1)
			return true
		})
	})
}
