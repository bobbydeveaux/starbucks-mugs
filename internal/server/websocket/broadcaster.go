// Package websocket provides the in-process WebSocket broadcaster for the
// TripWire dashboard server.  The Broadcaster fans newly ingested alerts out
// to all currently-connected browser clients without blocking the gRPC alert
// ingestion goroutine.
//
// Design notes
//
//   - Each WebSocket client has a dedicated buffered channel.  A non-blocking
//     send is used so that a slow or disconnected client never applies
//     back-pressure to the gRPC StreamAlerts goroutine.
//   - Subscriptions are tracked in a sync.Map to allow concurrent reads
//     without a global lock on the hot broadcast path.
//   - Closing a subscription signals the associated WebSocket pump goroutine
//     to exit cleanly.
package websocket

import (
	"context"
	"log/slog"
	"sync"
	"sync/atomic"

	"github.com/tripwire/agent/internal/server/storage"
)

// Broadcaster is the interface for fanning alert events out to subscribed
// WebSocket clients.
type Broadcaster interface {
	// Subscribe registers a new consumer and returns a channel on which
	// alerts will be delivered.  The channel is buffered; when the buffer
	// is full a subsequent Publish call drops the alert for that consumer
	// rather than blocking.  Call Unsubscribe to release resources.
	Subscribe(ctx context.Context) <-chan storage.Alert

	// Unsubscribe removes the subscription associated with ch and closes the
	// channel so the consumer loop exits cleanly.  It is safe to call
	// Unsubscribe after the broadcaster has been closed.
	Unsubscribe(ch <-chan storage.Alert)

	// Publish fans a to every current subscriber using a non-blocking send.
	// Subscribers whose channel buffer is full receive a dropped-alert log
	// entry rather than causing Publish to block.
	Publish(a storage.Alert)

	// Close removes all subscriptions, drains and closes every subscriber
	// channel, and releases internal resources.  After Close returns,
	// Publish is a no-op and Subscribe returns a closed channel.
	Close()
}

// InProcessBroadcaster is the single-instance, in-process Broadcaster
// implementation.  It is safe for concurrent use.
//
// For multi-instance dashboard deployments the same Broadcaster interface can
// be backed by a Redis pub/sub adapter without changing the alert service or
// WebSocket handler code.
type InProcessBroadcaster struct {
	subs      sync.Map        // map[<-chan storage.Alert]chan storage.Alert
	bufSize   int             // per-subscriber channel buffer depth
	logger    *slog.Logger
	closed    atomic.Bool
	closeOnce sync.Once
}

// NewBroadcaster creates an InProcessBroadcaster.
//
// bufSize is the per-subscriber channel buffer depth.  A value of 64 is
// sufficient for a 100 ms flush interval generating up to 640 alerts/s per
// subscriber before drops begin.  Pass 0 to use the default of 64.
func NewBroadcaster(logger *slog.Logger, bufSize int) *InProcessBroadcaster {
	if bufSize <= 0 {
		bufSize = 64
	}
	return &InProcessBroadcaster{
		bufSize: bufSize,
		logger:  logger,
	}
}

// Subscribe implements Broadcaster.
func (b *InProcessBroadcaster) Subscribe(ctx context.Context) <-chan storage.Alert {
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

// Unsubscribe implements Broadcaster.
func (b *InProcessBroadcaster) Unsubscribe(ch <-chan storage.Alert) {
	if actual, loaded := b.subs.LoadAndDelete(ch); loaded {
		close(actual.(chan storage.Alert))
	}
}

// Publish implements Broadcaster.
//
// The non-blocking select/default pattern ensures that a slow subscriber (or
// one whose context has already been cancelled) never stalls the gRPC
// StreamAlerts goroutine.
func (b *InProcessBroadcaster) Publish(a storage.Alert) {
	if b.closed.Load() {
		return
	}

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
}

// Close implements Broadcaster.
func (b *InProcessBroadcaster) Close() {
	b.closeOnce.Do(func() {
		b.closed.Store(true)
		b.subs.Range(func(key, value any) bool {
			b.subs.Delete(key)
			close(value.(chan storage.Alert))
			return true
		})
	})
}
