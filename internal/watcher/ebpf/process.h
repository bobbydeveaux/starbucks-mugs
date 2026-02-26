/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * internal/watcher/ebpf/process.h — Shared event struct for TripWire execve tracing.
 *
 * This header is included by the eBPF kernel program (process.bpf.c) and must
 * be mirrored by the Go userspace loader (process.go) so that binary layouts
 * are consistent across the ring-buffer boundary.
 *
 * Field sizes are chosen to keep the event within a single cache line (64 B)
 * while still carrying enough metadata for the TripWire alert pipeline.
 */

#ifndef TRIPWIRE_PROCESS_H
#define TRIPWIRE_PROCESS_H

#include <linux/types.h>

/* Maximum byte lengths for string fields (including the NUL terminator). */
#define TRIPWIRE_COMM_LEN    16   /* matches TASK_COMM_LEN in <linux/sched.h> */
#define TRIPWIRE_PATH_LEN   256   /* full exe path or argv[0] */
#define TRIPWIRE_ARGV_LEN   256   /* NUL-joined argv[0..N], space-joined */

/*
 * exec_event — kernel-populated ring buffer record.
 *
 * All integer fields use fixed-width types to guarantee identical layout on
 * 32-bit and 64-bit kernels. String fields are NUL-terminated C strings.
 *
 * Go mirror (process.go):
 *
 *   type execEvent struct {
 *       PID      uint32
 *       PPID     uint32
 *       UID      uint32
 *       GID      uint32
 *       Comm     [16]byte
 *       Filename [256]byte
 *       Argv     [256]byte
 *   }
 *
 * Total size: 4+4+4+4+16+256+256 = 544 bytes.
 */
struct exec_event {
    __u32 pid;                         /* tgid — matches getpid(2) */
    __u32 ppid;                        /* parent tgid */
    __u32 uid;                         /* real UID of the calling process */
    __u32 gid;                         /* real GID of the calling process */
    char  comm[TRIPWIRE_COMM_LEN];     /* short task name (≤ 15 chars + NUL) */
    char  filename[TRIPWIRE_PATH_LEN]; /* execve filename argument */
    char  argv[TRIPWIRE_ARGV_LEN];     /* argv[0..N] space-joined, NUL-terminated */
};

#endif /* TRIPWIRE_PROCESS_H */
