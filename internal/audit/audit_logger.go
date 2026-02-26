// Package audit provides a tamper-evident, append-only audit logger whose
// entries are SHA-256 hash-chained. Each log entry records a monotonically
// increasing sequence number, a timestamp, an arbitrary JSON payload, the
// previous entry's hash (prev_hash), and the SHA-256 hash of the entry's own
// content (event_hash).
//
// # Hash chain
//
// The event_hash for entry N is computed as:
//
//	SHA-256( JSON({seq, ts, payload, prev_hash}) )
//
// where the JSON encoding of those four fields is treated as a canonical byte
// sequence. The genesis entry (seq=1) uses a prev_hash of 64 ASCII zero
// characters ("000...0").
//
// # Append semantics
//
// Each entry is encoded as a single JSON line terminated by '\n'. The
// underlying file is opened with os.O_APPEND | os.O_CREATE | os.O_WRONLY so
// that every write is appended atomically by the OS (POSIX write(2) with
// O_APPEND guarantees a single atomic write up to PIPE_BUF bytes; JSON lines
// are kept small enough to satisfy this requirement in practice).
//
// # Thread safety
//
// Logger is safe for concurrent use. A mutex serialises all Append calls to
// maintain a consistent sequence number and prev_hash.
package audit

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"sync"
	"time"
)

const (
	// GenesisHash is the all-zero SHA-256 hex digest used as the prev_hash
	// of the very first (genesis) entry in the chain.
	GenesisHash = "0000000000000000000000000000000000000000000000000000000000000000"
)

// entry is the wire format for one audit log line.
type entry struct {
	Seq       int64           `json:"seq"`
	Timestamp time.Time       `json:"ts"`
	Payload   json.RawMessage `json:"payload"`
	PrevHash  string          `json:"prev_hash"`
	EventHash string          `json:"event_hash"`
}

// entryContent is the subset of entry fields that are hashed to produce
// EventHash. It deliberately excludes EventHash itself.
type entryContent struct {
	Seq       int64           `json:"seq"`
	Timestamp time.Time       `json:"ts"`
	Payload   json.RawMessage `json:"payload"`
	PrevHash  string          `json:"prev_hash"`
}

// Logger is a tamper-evident, append-only audit log writer. Create one with
// Open; do not copy after first use.
type Logger struct {
	mu       sync.Mutex
	file     *os.File
	prevHash string
	seq      int64
}

// Open opens (or creates) the log file at path and prepares the Logger for
// appending. If the file already contains entries, Open reads them all to
// restore the current sequence number and prev_hash so that the chain
// continues correctly. Returns an error if the file cannot be opened, any
// existing entry is malformed, or the existing chain is broken.
func Open(path string) (*Logger, error) {
	// First, read any existing entries to restore chain state.
	prevHash := GenesisHash
	seq := int64(0)

	// If the file already exists, scan it.
	if _, err := os.Stat(path); err == nil {
		f, err := os.Open(path)
		if err != nil {
			return nil, fmt.Errorf("audit: open for reading %q: %w", path, err)
		}
		scanner := bufio.NewScanner(f)
		// Allow lines up to 10 MiB (large payloads).
		buf := make([]byte, 0, 64*1024)
		scanner.Buffer(buf, 10*1024*1024)
		for scanner.Scan() {
			line := scanner.Bytes()
			if len(line) == 0 {
				continue
			}
			var e entry
			if err := json.Unmarshal(line, &e); err != nil {
				f.Close()
				return nil, fmt.Errorf("audit: malformed entry at seq %d: %w", seq+1, err)
			}
			// Verify the hash chain.
			computed := hashContent(entryContent{
				Seq:       e.Seq,
				Timestamp: e.Timestamp,
				Payload:   e.Payload,
				PrevHash:  e.PrevHash,
			})
			if computed != e.EventHash {
				f.Close()
				return nil, fmt.Errorf("audit: hash mismatch at seq %d: stored %q, computed %q",
					e.Seq, e.EventHash, computed)
			}
			if e.PrevHash != prevHash {
				f.Close()
				return nil, fmt.Errorf("audit: chain break at seq %d: expected prev_hash %q, got %q",
					e.Seq, prevHash, e.PrevHash)
			}
			prevHash = e.EventHash
			seq = e.Seq
		}
		f.Close()
		if err := scanner.Err(); err != nil {
			return nil, fmt.Errorf("audit: scanning existing log %q: %w", path, err)
		}
	}

	// Open the file for appending (creates it if absent).
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, fmt.Errorf("audit: open for appending %q: %w", path, err)
	}

	return &Logger{
		file:     f,
		prevHash: prevHash,
		seq:      seq,
	}, nil
}

// Append writes a new tamper-evident entry to the log. payload must be valid
// JSON; passing nil records a JSON null payload. Append is safe to call from
// multiple goroutines.
//
// The returned Entry contains the assigned sequence number, timestamp,
// computed EventHash, and PrevHash so callers can record chain metadata
// without re-reading the file.
func (l *Logger) Append(payload json.RawMessage) (Entry, error) {
	if payload == nil {
		payload = json.RawMessage("null")
	}

	l.mu.Lock()
	defer l.mu.Unlock()

	seq := l.seq + 1
	ts := time.Now().UTC()

	prevHash := l.prevHash // capture before mutation

	content := entryContent{
		Seq:       seq,
		Timestamp: ts,
		Payload:   payload,
		PrevHash:  prevHash,
	}
	eventHash := hashContent(content)

	e := entry{
		Seq:       seq,
		Timestamp: ts,
		Payload:   payload,
		PrevHash:  prevHash,
		EventHash: eventHash,
	}

	line, err := json.Marshal(e)
	if err != nil {
		return Entry{}, fmt.Errorf("audit: marshal entry: %w", err)
	}
	// Append newline so each entry is a self-contained JSON line.
	line = append(line, '\n')

	if _, err := l.file.Write(line); err != nil {
		return Entry{}, fmt.Errorf("audit: write entry: %w", err)
	}

	l.seq = seq
	l.prevHash = eventHash

	return Entry{
		Seq:       seq,
		Timestamp: ts,
		Payload:   payload,
		PrevHash:  prevHash,
		EventHash: eventHash,
	}, nil
}

// Close flushes any OS-level buffers and closes the underlying file.
func (l *Logger) Close() error {
	l.mu.Lock()
	defer l.mu.Unlock()
	if err := l.file.Sync(); err != nil {
		// Best-effort sync; report close error regardless.
		_ = l.file.Close()
		return fmt.Errorf("audit: sync: %w", err)
	}
	return l.file.Close()
}

// Entry is the public representation of one audit log entry returned by
// Append and Verify.
type Entry struct {
	Seq       int64           `json:"seq"`
	Timestamp time.Time       `json:"ts"`
	Payload   json.RawMessage `json:"payload"`
	PrevHash  string          `json:"prev_hash"`
	EventHash string          `json:"event_hash"`
}

// Verify reads the log file at path and checks the full hash chain. It
// returns the ordered slice of entries on success, or the first chain error
// encountered. An empty file is valid and returns an empty slice.
func Verify(path string) ([]Entry, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("audit: verify open %q: %w", path, err)
	}
	defer f.Close()

	var entries []Entry
	prevHash := GenesisHash
	scanner := bufio.NewScanner(f)
	buf := make([]byte, 0, 64*1024)
	scanner.Buffer(buf, 10*1024*1024)

	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		var e entry
		if err := json.Unmarshal(line, &e); err != nil {
			return nil, fmt.Errorf("audit: malformed entry: %w", err)
		}

		// Verify prev_hash linkage.
		if e.PrevHash != prevHash {
			return nil, fmt.Errorf("audit: chain break at seq %d: expected prev_hash %q, got %q",
				e.Seq, prevHash, e.PrevHash)
		}

		// Recompute and verify event_hash.
		computed := hashContent(entryContent{
			Seq:       e.Seq,
			Timestamp: e.Timestamp,
			Payload:   e.Payload,
			PrevHash:  e.PrevHash,
		})
		if computed != e.EventHash {
			return nil, fmt.Errorf("audit: hash mismatch at seq %d: stored %q, computed %q",
				e.Seq, e.EventHash, computed)
		}

		entries = append(entries, Entry{
			Seq:       e.Seq,
			Timestamp: e.Timestamp,
			Payload:   e.Payload,
			PrevHash:  e.PrevHash,
			EventHash: e.EventHash,
		})
		prevHash = e.EventHash
	}

	return entries, scanner.Err()
}

// hashContent computes the SHA-256 hex digest of the JSON-marshalled
// entryContent. It panics on marshal failure, which cannot happen for
// well-formed entryContent values.
func hashContent(c entryContent) string {
	raw, err := json.Marshal(c)
	if err != nil {
		// entryContent fields are all JSON-serialisable; this is unreachable.
		panic(fmt.Sprintf("audit: marshal entryContent: %v", err))
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}
