// SPDX-License-Identifier: GPL-2.0-or-later
//
// internal/watcher/ebpf/process.bpf.c — TripWire eBPF kernel program
//
// This program attaches to the sys_enter_execve and sys_enter_execveat
// tracepoints and writes a structured exec_event to a BPF ring buffer each
// time any process calls either syscall.  The companion Go userspace code
// (internal/watcher/ebpf/process.go) loads this object, reads the ring
// buffer, and converts raw kernel structs into typed AlertEvents.
//
// ─── Build instructions ──────────────────────────────────────────────────────
//
//   clang -O2 -g -Wall \
//     -target bpf \
//     -D__TARGET_ARCH_x86 \
//     -I/usr/include/$(uname -m)-linux-gnu \
//     -I. \
//     -c internal/watcher/ebpf/process.bpf.c \
//     -o internal/watcher/ebpf/process.bpf.o
//
//   # Strip debug info for a smaller object (optional):
//   llvm-strip -g internal/watcher/ebpf/process.bpf.o
//
// The resulting .bpf.o file is embedded into the Go binary via go:embed in
// internal/watcher/ebpf/process.go so that no runtime compilation is needed.
//
// ─── Kernel requirements ─────────────────────────────────────────────────────
//
//   • Linux ≥ 5.8  — BPF ring buffer (BPF_MAP_TYPE_RINGBUF).
//   • CAP_BPF (Linux ≥ 5.8) or CAP_SYS_ADMIN (older kernels).
//   • CONFIG_BPF_SYSCALL=y, CONFIG_DEBUG_INFO_BTF=y (for CO-RE).
//
// ─── Event struct ────────────────────────────────────────────────────────────
//
//   See process.h for the shared exec_event definition.
//
// ─────────────────────────────────────────────────────────────────────────────

#include "vmlinux.h"          /* auto-generated kernel type definitions (CO-RE) */
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#include "process.h"

// ─── Ring-buffer map ─────────────────────────────────────────────────────────
//
// The ring buffer is preferred over perf event arrays for high-throughput
// kernel→user transfer: it is lock-free, avoids per-CPU memory waste, and
// supports variable-length records.  16 MiB is large enough to absorb several
// seconds of burst load on a busy system.

struct {
    __uint(type,        BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 1 << 24);  /* 16 MiB */
} execve_events SEC(".maps");

// ─── Shared argv-join helper ─────────────────────────────────────────────────

/*
 * fill_argv reads up to MAX_ARGS arguments from the user-space argv array
 * starting at argv_ptr and writes them space-joined into buf (max len bytes).
 * The result is always NUL-terminated.  This helper is called by both
 * trace_execve and trace_execveat.
 */
#define MAX_ARGS 16

static __always_inline void fill_argv(
    char *buf, int len,
    const char *const *argv_ptr)
{
    int pos = 0;

#pragma unroll
    for (int i = 0; i < MAX_ARGS && pos < len - 1; i++) {
        const char *arg = NULL;
        bpf_probe_read_user(&arg, sizeof(arg), &argv_ptr[i]);
        if (!arg)
            break;

        /* Add a space separator between arguments. */
        if (i > 0 && pos < len - 1)
            buf[pos++] = ' ';

        /* Read the argument string into the remaining buffer space. */
        int remaining = len - pos - 1;
        if (remaining <= 0)
            break;

        int n = bpf_probe_read_user_str(&buf[pos], remaining, arg);
        if (n > 0)
            pos += n - 1; /* n includes the NUL; advance past chars only */
    }

    /* Guarantee NUL termination. */
    if (pos < len)
        buf[pos] = '\0';
}

// ─── Shared event-fill helper ────────────────────────────────────────────────

/*
 * fill_event populates a pre-reserved exec_event with process metadata and
 * the filename / argv from user space.
 */
static __always_inline void fill_event(
    struct exec_event *e,
    const char        *filename_ptr,
    const char *const *argv_ptr)
{
    struct task_struct *task;
    __u64 pid_tgid, uid_gid;

    pid_tgid = bpf_get_current_pid_tgid();
    uid_gid  = bpf_get_current_uid_gid();

    e->pid = (__u32)(pid_tgid >> 32);
    e->uid = (__u32)(uid_gid  & 0xFFFFFFFF);
    e->gid = (__u32)(uid_gid  >> 32);

    /* Retrieve PPID from the task struct via CO-RE. */
    task   = (struct task_struct *)bpf_get_current_task_btf();
    e->ppid = (__u32)BPF_CORE_READ(task, real_parent, tgid);

    /* Short task name is already in kernel memory. */
    bpf_get_current_comm(e->comm, sizeof(e->comm));

    /* Read the filename argument (execve path) from user space. */
    bpf_probe_read_user_str(e->filename, sizeof(e->filename), filename_ptr);

    /* Build the NUL-terminated, space-joined argv string. */
    fill_argv(e->argv, sizeof(e->argv), argv_ptr);
}

// ─── Tracepoint: sys_enter_execve ────────────────────────────────────────────
//
//   long execve(const char *filename,
//               const char *const argv[],
//               const char *const envp[]);
//
//   ctx->args[0] = filename
//   ctx->args[1] = argv
//   ctx->args[2] = envp  (ignored)

SEC("tracepoint/syscalls/sys_enter_execve")
int trace_execve(struct trace_event_raw_sys_enter *ctx)
{
    struct exec_event *e;

    e = bpf_ringbuf_reserve(&execve_events, sizeof(*e), 0);
    if (!e)
        return 0;   /* ring buffer full; drop silently */

    fill_event(e,
               (const char *)(unsigned long)ctx->args[0],
               (const char *const *)(unsigned long)ctx->args[1]);

    bpf_ringbuf_submit(e, 0);
    return 0;
}

// ─── Tracepoint: sys_enter_execveat ──────────────────────────────────────────
//
//   long execveat(int dirfd,
//                 const char *pathname,
//                 const char *const argv[],
//                 const char *const envp[],
//                 int flags);
//
//   ctx->args[0] = dirfd      (ignored; we only capture the path)
//   ctx->args[1] = pathname
//   ctx->args[2] = argv
//   ctx->args[3] = envp       (ignored)
//   ctx->args[4] = flags      (ignored)

SEC("tracepoint/syscalls/sys_enter_execveat")
int trace_execveat(struct trace_event_raw_sys_enter *ctx)
{
    struct exec_event *e;

    e = bpf_ringbuf_reserve(&execve_events, sizeof(*e), 0);
    if (!e)
        return 0;

    fill_event(e,
               (const char *)(unsigned long)ctx->args[1],
               (const char *const *)(unsigned long)ctx->args[2]);

    bpf_ringbuf_submit(e, 0);
    return 0;
}

// ─── License ─────────────────────────────────────────────────────────────────
//
// GPL-2.0-or-later allows this program to call GPL-only BPF helper functions
// such as bpf_probe_read_user_str. The kernel verifier enforces this.

char LICENSE[] SEC("license") = "GPL";
