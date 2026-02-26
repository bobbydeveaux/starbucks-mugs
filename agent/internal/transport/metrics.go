// Package transport – Prometheus metrics for the gRPC transport layer.
//
// # Overview
//
// Metrics tracks operational counters and gauges for the transport client.
// All fields are updated atomically so they can be read concurrently from an
// HTTP handler without holding any additional lock.
//
// # Prometheus text format
//
// Handler returns an [net/http.Handler] that serves the registered metrics in
// the standard Prometheus text exposition format on every GET request.  Wire it
// into your HTTP mux at /metrics (or any other path you prefer):
//
//	m := transport.NewMetrics()
//	http.Handle("/metrics", m.Handler())
//
// # Metric catalogue
//
//	transport_connection_attempts_total   – counter: times the client tried to open a gRPC connection
//	transport_connection_errors_total     – counter: connection attempts that failed
//	transport_reconnect_attempts_total    – counter: reconnect cycles after a transient error
//	transport_agent_registrations_total   – counter: RegisterAgent RPCs attempted
//	transport_registration_errors_total   – counter: RegisterAgent RPCs that returned an error
//	transport_alerts_sent_total           – counter: AgentEvent messages delivered to the server
//	transport_stream_send_errors_total    – counter: errors returned by stream.Send
//	transport_stream_recv_errors_total    – counter: errors returned by stream.Recv (non-EOF)
//	transport_connected                   – gauge:   1 when a stream is active, 0 otherwise
package transport

import (
	"fmt"
	"io"
	"net/http"
	"sync/atomic"
)

// Metrics holds all Prometheus counters and gauges for the transport layer.
// The zero value is ready to use; all counters start at zero.
//
// Create one with [NewMetrics] (which pre-fills the metric metadata) or embed a
// zero value when you only need to call [Metrics.Handler].
type Metrics struct {
	// Counters
	ConnectionAttempts   atomic.Int64
	ConnectionErrors     atomic.Int64
	ReconnectAttempts    atomic.Int64
	AgentRegistrations   atomic.Int64
	RegistrationErrors   atomic.Int64
	AlertsSent           atomic.Int64
	StreamSendErrors     atomic.Int64
	StreamRecvErrors     atomic.Int64

	// Gauge (0 or 1)
	Connected atomic.Int64
}

// NewMetrics allocates a new [Metrics] value with all counters at zero.
// The returned pointer can be passed to [WithMetrics] when constructing a
// [Client] and its [Metrics.Handler] can be served on any HTTP mux.
func NewMetrics() *Metrics {
	return &Metrics{}
}

// metricLine is a single Prometheus metric family descriptor plus its current value.
type metricLine struct {
	help   string
	kind   string // "counter" or "gauge"
	name   string
	value  int64
}

// snapshot captures the current values of all metrics in a consistent order.
func (m *Metrics) snapshot() []metricLine {
	return []metricLine{
		{
			help:  "Total number of gRPC connection attempts made by the transport client.",
			kind:  "counter",
			name:  "transport_connection_attempts_total",
			value: m.ConnectionAttempts.Load(),
		},
		{
			help:  "Total number of gRPC connection attempts that returned an error.",
			kind:  "counter",
			name:  "transport_connection_errors_total",
			value: m.ConnectionErrors.Load(),
		},
		{
			help:  "Total number of reconnection cycles initiated after a transient error.",
			kind:  "counter",
			name:  "transport_reconnect_attempts_total",
			value: m.ReconnectAttempts.Load(),
		},
		{
			help:  "Total number of RegisterAgent RPCs attempted.",
			kind:  "counter",
			name:  "transport_agent_registrations_total",
			value: m.AgentRegistrations.Load(),
		},
		{
			help:  "Total number of RegisterAgent RPCs that returned an error.",
			kind:  "counter",
			name:  "transport_registration_errors_total",
			value: m.RegistrationErrors.Load(),
		},
		{
			help:  "Total number of AgentEvent messages successfully delivered to the dashboard.",
			kind:  "counter",
			name:  "transport_alerts_sent_total",
			value: m.AlertsSent.Load(),
		},
		{
			help:  "Total number of stream.Send calls that returned an error.",
			kind:  "counter",
			name:  "transport_stream_send_errors_total",
			value: m.StreamSendErrors.Load(),
		},
		{
			help:  "Total number of stream.Recv calls that returned a non-EOF error.",
			kind:  "counter",
			name:  "transport_stream_recv_errors_total",
			value: m.StreamRecvErrors.Load(),
		},
		{
			help:  "1 when a bidirectional alert stream is currently active, 0 otherwise.",
			kind:  "gauge",
			name:  "transport_connected",
			value: m.Connected.Load(),
		},
	}
}

// Handler returns an [http.Handler] that writes all transport metrics in the
// Prometheus text exposition format on every GET request.
//
// The content type is set to "text/plain; version=0.0.4" as required by
// the Prometheus specification so that a vanilla Prometheus scraper will
// parse the output correctly.
func (m *Metrics) Handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		writeMetrics(w, m.snapshot())
	})
}

// writeMetrics serialises lines into Prometheus text exposition format.
func writeMetrics(w io.Writer, lines []metricLine) {
	for _, l := range lines {
		fmt.Fprintf(w, "# HELP %s %s\n", l.name, l.help)
		fmt.Fprintf(w, "# TYPE %s %s\n", l.name, l.kind)
		fmt.Fprintf(w, "%s %d\n", l.name, l.value)
	}
}
