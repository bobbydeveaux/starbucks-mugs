//go:build !linux

package watcher

import (
	"context"
	"fmt"
	"os"
	"time"
)

// startPlatformWatcher is the fallback implementation for platforms that do
// not support inotify (i.e. non-Linux). It polls each path every 500 ms and
// detects changes by comparing modification time and size. The events channel
// is NOT closed by this function; it returns nil on clean shutdown or a
// non-nil error on failure.
func startPlatformWatcher(ctx context.Context, paths []string, events chan<- FileEvent) error {
	type fileState struct {
		size    int64
		modTime time.Time
		exists  bool
	}

	states := make(map[string]fileState, len(paths))

	// Initialise state for all known paths.
	for _, p := range paths {
		info, err := os.Stat(p)
		if err != nil {
			if os.IsNotExist(err) {
				states[p] = fileState{exists: false}
				continue
			}
			return fmt.Errorf("file watcher: stat %q: %w", p, err)
		}
		states[p] = fileState{
			size:    info.Size(),
			modTime: info.ModTime(),
			exists:  true,
		}
	}

	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			for _, p := range paths {
				info, err := os.Stat(p)
				prev := states[p]

				if err != nil {
					if os.IsNotExist(err) && prev.exists {
						// File was deleted.
						states[p] = fileState{exists: false}
						select {
						case events <- FileEvent{
							FilePath:  p,
							EventType: EventDelete,
							Timestamp: time.Now(),
						}:
						default:
						}
					}
					continue
				}

				if !prev.exists {
					// File was created.
					states[p] = fileState{
						size:    info.Size(),
						modTime: info.ModTime(),
						exists:  true,
					}
					select {
					case events <- FileEvent{
						FilePath:  p,
						EventType: EventCreate,
						Timestamp: time.Now(),
					}:
					default:
					}
					continue
				}

				if info.ModTime() != prev.modTime || info.Size() != prev.size {
					// File was modified.
					states[p] = fileState{
						size:    info.Size(),
						modTime: info.ModTime(),
						exists:  true,
					}
					select {
					case events <- FileEvent{
						FilePath:  p,
						EventType: EventWrite,
						Timestamp: time.Now(),
					}:
					default:
					}
				}
			}
		}
	}
}
