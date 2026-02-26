// bpfobject_embed_linux.go — embedded BPF object variant.
//
// This file is compiled when the "bpf_embedded" build tag is set, which
// requires the pre-compiled process.bpf.o to exist in this directory.
//
// Build sequence:
//
//	make -C internal/watcher/ebpf   # compile process.bpf.c → process.bpf.o
//	go build -tags bpf_embedded ./internal/watcher/ebpf/...
//
//go:build linux && bpf_embedded

package ebpf

import _ "embed"

//go:embed process.bpf.o
var _embeddedBPFObject []byte

func init() {
	// Assign the embedded object bytes to the package variable so that
	// ProcessWatcher.Start picks them up without requiring SetBPFObject.
	bpfObjectBytes = _embeddedBPFObject
}
