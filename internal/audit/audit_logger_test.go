package audit_test

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/audit"
)

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

func tmpLog(t *testing.T) string {
	t.Helper()
	return filepath.Join(t.TempDir(), "audit.log")
}

// openLogger opens the audit log and registers a cleanup to close it.
func openLogger(t *testing.T, path string) *audit.Logger {
	t.Helper()
	l, err := audit.Open(path)
	if err != nil {
		t.Fatalf("audit.Open(%q): %v", path, err)
	}
	t.Cleanup(func() { _ = l.Close() })
	return l
}

func mustAppend(t *testing.T, l *audit.Logger, payload string) audit.Entry {
	t.Helper()
	e, err := l.Append(json.RawMessage(payload))
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	return e
}

// --------------------------------------------------------------------------
// Basic append tests
// --------------------------------------------------------------------------

func TestAppend_SingleEntry(t *testing.T) {
	l := openLogger(t, tmpLog(t))
	e := mustAppend(t, l, `{"event":"test"}`)

	if e.Seq != 1 {
		t.Errorf("seq = %d, want 1", e.Seq)
	}
	if e.PrevHash != audit.GenesisHash {
		t.Errorf("prev_hash = %q, want genesis hash", e.PrevHash)
	}
	if len(e.EventHash) != 64 {
		t.Errorf("event_hash length = %d, want 64", len(e.EventHash))
	}
	if e.Timestamp.IsZero() {
		t.Error("timestamp must not be zero")
	}
}

func TestAppend_MultipleEntries_Chain(t *testing.T) {
	l := openLogger(t, tmpLog(t))

	payloads := []string{
		`{"type":"FILE","rule":"etc-passwd"}`,
		`{"type":"NETWORK","port":22}`,
		`{"type":"PROCESS","name":"bash"}`,
	}

	entries := make([]audit.Entry, len(payloads))
	for i, p := range payloads {
		entries[i] = mustAppend(t, l, p)
	}

	// First entry must link to the genesis hash.
	if entries[0].PrevHash != audit.GenesisHash {
		t.Errorf("entry[0].prev_hash = %q, want genesis", entries[0].PrevHash)
	}
	// Subsequent entries must link to the previous entry's event_hash.
	for i := 1; i < len(entries); i++ {
		if entries[i].PrevHash != entries[i-1].EventHash {
			t.Errorf("entry[%d].prev_hash = %q, want entry[%d].event_hash = %q",
				i, entries[i].PrevHash, i-1, entries[i-1].EventHash)
		}
	}
	// Sequence numbers must be monotonically increasing starting at 1.
	for i, e := range entries {
		if e.Seq != int64(i+1) {
			t.Errorf("entry[%d].seq = %d, want %d", i, e.Seq, i+1)
		}
	}
}

func TestAppend_HashMatchesManualComputation(t *testing.T) {
	l := openLogger(t, tmpLog(t))
	e := mustAppend(t, l, `{"x":1}`)

	// Manually re-derive the hash using the same struct layout as the logger.
	// The Timestamp field must use time.Time so json.Marshal produces the
	// identical RFC3339Nano encoding.
	type entryContent struct {
		Seq       int64           `json:"seq"`
		Timestamp time.Time       `json:"ts"`
		Payload   json.RawMessage `json:"payload"`
		PrevHash  string          `json:"prev_hash"`
	}
	c := entryContent{
		Seq:       e.Seq,
		Timestamp: e.Timestamp,
		Payload:   e.Payload,
		PrevHash:  e.PrevHash,
	}
	raw, err := json.Marshal(c)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	sum := sha256.Sum256(raw)
	want := hex.EncodeToString(sum[:])

	if e.EventHash != want {
		t.Errorf("event_hash = %q, want %q", e.EventHash, want)
	}
}

func TestAppend_NilPayload(t *testing.T) {
	l := openLogger(t, tmpLog(t))
	e, err := l.Append(nil)
	if err != nil {
		t.Fatalf("Append(nil): %v", err)
	}
	if string(e.Payload) != "null" {
		t.Errorf("payload = %q, want %q", string(e.Payload), "null")
	}
}

func TestAppend_GenesisHash_IsAllZeros(t *testing.T) {
	const wantLen = 64
	if len(audit.GenesisHash) != wantLen {
		t.Errorf("GenesisHash length = %d, want %d", len(audit.GenesisHash), wantLen)
	}
	for _, c := range audit.GenesisHash {
		if c != '0' {
			t.Errorf("GenesisHash contains non-zero character %q in %q", c, audit.GenesisHash)
			break
		}
	}
}

// --------------------------------------------------------------------------
// Persistence: re-opening continues the chain
// --------------------------------------------------------------------------

func TestOpen_ResumeExistingChain(t *testing.T) {
	path := tmpLog(t)

	// First session: write two entries.
	l1 := openLogger(t, path)
	mustAppend(t, l1, `{"session":1,"event":1}`)
	e2 := mustAppend(t, l1, `{"session":1,"event":2}`)
	if err := l1.Close(); err != nil {
		t.Fatalf("l1.Close: %v", err)
	}

	// Second session: open the same file and write a third entry.
	l2 := openLogger(t, path)
	e3 := mustAppend(t, l2, `{"session":2,"event":3}`)

	// The third entry's prev_hash must equal the second entry's event_hash.
	if e3.PrevHash != e2.EventHash {
		t.Errorf("e3.prev_hash = %q, want e2.event_hash = %q", e3.PrevHash, e2.EventHash)
	}
	if e3.Seq != 3 {
		t.Errorf("e3.seq = %d, want 3", e3.Seq)
	}
}

// --------------------------------------------------------------------------
// Verify: correct chain passes
// --------------------------------------------------------------------------

func TestVerify_EmptyFile(t *testing.T) {
	path := tmpLog(t)
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	f.Close()

	entries, err := audit.Verify(path)
	if err != nil {
		t.Fatalf("Verify(empty): %v", err)
	}
	if len(entries) != 0 {
		t.Errorf("expected 0 entries, got %d", len(entries))
	}
}

func TestVerify_ValidChain(t *testing.T) {
	path := tmpLog(t)
	l := openLogger(t, path)
	for i := 0; i < 5; i++ {
		mustAppend(t, l, `{"i":`+string(rune('0'+i))+`}`)
	}
	// Explicitly close so the OS flushes before we verify.
	if err := l.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	entries, err := audit.Verify(path)
	if err != nil {
		t.Fatalf("Verify: %v", err)
	}
	if len(entries) != 5 {
		t.Errorf("Verify returned %d entries, want 5", len(entries))
	}
	if entries[0].PrevHash != audit.GenesisHash {
		t.Errorf("entries[0].prev_hash = %q, want genesis", entries[0].PrevHash)
	}
	for i, e := range entries {
		if e.Seq != int64(i+1) {
			t.Errorf("entries[%d].seq = %d, want %d", i, e.Seq, i+1)
		}
	}
	for i := 1; i < len(entries); i++ {
		if entries[i].PrevHash != entries[i-1].EventHash {
			t.Errorf("entries[%d].prev_hash breaks chain", i)
		}
	}
}

// --------------------------------------------------------------------------
// Verify: tamper detection
// --------------------------------------------------------------------------

func TestVerify_DetectsModifiedPayload(t *testing.T) {
	path := tmpLog(t)
	l := openLogger(t, path)
	mustAppend(t, l, `{"original":true}`)
	mustAppend(t, l, `{"second":true}`)
	if err := l.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	// Flip true→false in the first entry's payload. The stored hash will no
	// longer match the recomputed hash.
	corrupted := strings.Replace(string(data), `"original":true`, `"original":false`, 1)
	if err := os.WriteFile(path, []byte(corrupted), 0o600); err != nil {
		t.Fatal(err)
	}

	_, err = audit.Verify(path)
	if err == nil {
		t.Fatal("Verify should have detected tampered payload, got nil error")
	}
}

func TestVerify_DetectsDeletedEntry(t *testing.T) {
	path := tmpLog(t)
	l := openLogger(t, path)
	mustAppend(t, l, `{"event":1}`)
	mustAppend(t, l, `{"event":2}`)
	mustAppend(t, l, `{"event":3}`)
	if err := l.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	// Remove the first line to simulate an entry being deleted. The second
	// entry's prev_hash will no longer equal the genesis hash.
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	idx := strings.Index(string(data), "\n")
	if idx < 0 {
		t.Fatal("expected at least one newline-terminated entry")
	}
	remaining := string(data)[idx+1:]
	if err := os.WriteFile(path, []byte(remaining), 0o600); err != nil {
		t.Fatal(err)
	}

	_, err = audit.Verify(path)
	if err == nil {
		t.Fatal("Verify should have detected missing entry, got nil error")
	}
}

func TestVerify_DetectsModifiedEventHash(t *testing.T) {
	path := tmpLog(t)
	l := openLogger(t, path)
	mustAppend(t, l, `{"event":1}`)
	if err := l.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	type wireEntry struct {
		Seq       int64           `json:"seq"`
		Timestamp time.Time       `json:"ts"`
		Payload   json.RawMessage `json:"payload"`
		PrevHash  string          `json:"prev_hash"`
		EventHash string          `json:"event_hash"`
	}
	var e wireEntry
	line := strings.TrimRight(string(data), "\n")
	if err := json.Unmarshal([]byte(line), &e); err != nil {
		t.Fatalf("parse: %v", err)
	}

	// Corrupt the event_hash by changing the first hex digit to a different
	// valid hex digit. This always produces a well-formed JSON string.
	hashBytes := []byte(e.EventHash)
	if hashBytes[0] == '0' {
		hashBytes[0] = '1'
	} else {
		hashBytes[0] = '0'
	}
	e.EventHash = string(hashBytes)

	corrupted, err := json.Marshal(e)
	if err != nil {
		t.Fatalf("marshal corrupted entry: %v", err)
	}
	if err := os.WriteFile(path, append(corrupted, '\n'), 0o600); err != nil {
		t.Fatal(err)
	}

	_, err = audit.Verify(path)
	if err == nil {
		t.Fatal("Verify should have detected corrupted event_hash, got nil error")
	}
}

// --------------------------------------------------------------------------
// Open: rejects a corrupted existing log
// --------------------------------------------------------------------------

func TestOpen_RejectsCorruptedLog(t *testing.T) {
	path := tmpLog(t)

	l := openLogger(t, path)
	mustAppend(t, l, `{"event":1}`)
	if err := l.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	// Mutate the payload after the initial close so the stored hash is stale.
	corrupted := strings.Replace(string(data), `"event":1`, `"event":99`, 1)
	if err := os.WriteFile(path, []byte(corrupted), 0o600); err != nil {
		t.Fatal(err)
	}

	_, err = audit.Open(path)
	if err == nil {
		t.Fatal("Open should have rejected corrupted log, got nil error")
	}
}

// --------------------------------------------------------------------------
// Concurrent safety
// --------------------------------------------------------------------------

func TestAppend_ConcurrentSafe(t *testing.T) {
	path := tmpLog(t)
	l := openLogger(t, path)

	const goroutines = 10
	const perGoroutine = 20

	var wg sync.WaitGroup
	for i := 0; i < goroutines; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			for j := 0; j < perGoroutine; j++ {
				payload := json.RawMessage(`{"gid":` + string(rune('0'+id)) + `}`)
				if _, err := l.Append(payload); err != nil {
					t.Errorf("goroutine %d Append: %v", id, err)
					return
				}
			}
		}(i)
	}
	wg.Wait()

	// Explicitly close before verifying so all data is flushed to disk.
	if err := l.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	entries, err := audit.Verify(path)
	if err != nil {
		t.Fatalf("Verify after concurrent appends: %v", err)
	}
	if len(entries) != goroutines*perGoroutine {
		t.Errorf("expected %d entries, got %d", goroutines*perGoroutine, len(entries))
	}
}
