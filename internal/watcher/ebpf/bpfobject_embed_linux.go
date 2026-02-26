// bpfobject_embed_linux.go — retained for backward compatibility with the
// bpf_embedded build tag.
//
// The BPF object is now embedded unconditionally in process.go via //go:embed,
// so this file has no effect. It is preserved so that existing build scripts
// using -tags bpf_embedded continue to compile without error.

//go:build linux && bpf_embedded

package ebpf
