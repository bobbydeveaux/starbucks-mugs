// BPF object loader and ring-buffer reader for the TripWire eBPF process watcher.
//
// This file implements:
//   - ELF parsing of pre-compiled BPF objects (process.bpf.o)
//   - BPF map creation (BPF_MAP_TYPE_RINGBUF)
//   - BPF instruction patching (LD_IMM64 map-fd relocations)
//   - BPF program loading (BPF_PROG_LOAD)
//   - Tracepoint attachment (perf_event_open + PERF_EVENT_IOC_SET_BPF)
//   - Ring-buffer reading (mmap + atomic consumer/producer positions)
//
// All BPF operations use raw Linux syscalls so that this package requires no
// external dependencies beyond the Go standard library.
//
//go:build linux

package ebpf

import (
	"bytes"
	"context"
	"debug/elf"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"syscall"
	"time"
	"unsafe"
)

// ─── BPF syscall constants ─────────────────────────────────────────────────────
//
// Values from <linux/bpf.h>. Never change.

const (
	// BPF command codes (first argument to the bpf(2) syscall).
	bpfCmdMapCreate uintptr = 0
	bpfCmdProgLoad  uintptr = 5

	// BPF map types.
	bpfMapTypeRingBuf uint32 = 27

	// BPF program types.
	bpfProgTypeTracepoint uint32 = 5

	// BPF instruction opcode for 64-bit immediate load (BPF_LD|BPF_IMM|BPF_DW).
	bpfOpLdImm64 uint8 = 0x18

	// BPF_PSEUDO_MAP_FD: src_reg value that marks a map-fd reference.
	bpfPseudoMapFD uint8 = 1

	// Ring-buffer record header flags (upper bits of the len field).
	bpfRingBufBusyBit    uint32 = 1 << 31
	bpfRingBufDiscardBit uint32 = 1 << 30
	bpfRingBufHdrSize    uint32 = 8 // sizeof(struct bpf_ringbuf_hdr)

	// Verifier log verbosity.
	bpfLogLevel uint32 = 1
)

// ─── Perf event constants ──────────────────────────────────────────────────────
//
// Values from <linux/perf_event.h>. Never change.

const (
	perfTypeTracepoint uint32 = 1

	// ioctl codes for perf event control (computed from _IO/_IOW macros).
	perfEventIOCEnable = 0x00002400 // _IO ('$', 0)
	perfEventIOCSetBPF = 0x40044408 // _IOW('$', 8, __u32)

	// Path under debugfs/tracefs where tracepoint IDs are published.
	tracepointIDDir = "/sys/kernel/debug/tracing/events"
)

// ─── Syscall wrappers ─────────────────────────────────────────────────────────

// bpfSyscall wraps the Linux bpf(2) syscall and returns the resulting fd or
// an errno-wrapped error.
func bpfSyscall(cmd uintptr, attr unsafe.Pointer, attrSize uintptr) (int, error) {
	fd, _, errno := syscall.RawSyscall(syscall.SYS_BPF, cmd, uintptr(attr), attrSize)
	if errno != 0 {
		return -1, errno
	}
	return int(fd), nil
}

// perfEventOpen wraps the perf_event_open(2) syscall.
func perfEventOpen(attr *perfEventAttr, pid, cpu, groupFD int) (int, error) {
	fd, _, errno := syscall.RawSyscall6(
		syscall.SYS_PERF_EVENT_OPEN,
		uintptr(unsafe.Pointer(attr)),
		uintptr(pid),
		uintptr(cpu),
		uintptr(groupFD),
		0, // flags
		0,
	)
	if errno != 0 {
		return -1, errno
	}
	return int(fd), nil
}

// ioctlFd calls ioctl(fd, req, arg) and returns any error.
func ioctlFd(fd int, req uint, arg uintptr) error {
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd), uintptr(req), arg)
	if errno != 0 {
		return errno
	}
	return nil
}

// ─── Kernel ABI attribute structs ─────────────────────────────────────────────

// bpfMapCreateAttr is the bpf(BPF_MAP_CREATE, …) attribute.
// Matches the map-create union member of struct bpf_attr.
type bpfMapCreateAttr struct {
	mapType    uint32
	keySize    uint32
	valueSize  uint32
	maxEntries uint32
	mapFlags   uint32
	_          [76]byte // padding to 96 B (kernel expects ≥ 16 B but we send more for safety)
}

// bpfProgLoadAttr is the bpf(BPF_PROG_LOAD, …) attribute.
// Matches the prog-load union member of struct bpf_attr.
type bpfProgLoadAttr struct {
	progType           uint32
	insnCnt            uint32
	insns              uint64 // *bpfInsn
	license            uint64 // *byte (NUL-terminated)
	logLevel           uint32
	logSize            uint32
	logBuf             uint64 // *byte
	kernVersion        uint32
	progFlags          uint32
	progName           [16]byte
	progIfindex        uint32
	expectedAttachType uint32
	progBTFFd          uint32
	funcInfoRecSize    uint32
	funcInfo           uint64
	funcInfoCnt        uint32
	lineInfoRecSize    uint32
	lineInfo           uint64
	lineInfoCnt        uint32
	attachBTFId        uint32
	attachProgFd       uint32
}

// perfEventAttr is the subset of struct perf_event_attr used for tracepoint
// attachment. We only set the fields required by TripWire.
type perfEventAttr struct {
	eventType  uint32 // .type
	size       uint32 // .size (must be sizeof(struct perf_event_attr))
	config     uint64 // .config = tracepoint ID
	sampleFreq uint64 // .sample_period / .sample_freq (unused; zero)
	sampleType uint64 // .sample_type (unused; zero)
	readFormat uint64 // .read_format (unused; zero)
	// Bitfield word: bit 0 = disabled, bit 1 = inherit, …
	bits uint64
	// Remaining fields zero (not used for tracepoints without sampling).
	wakeupEventsOrWatermark uint32
	bpType                  uint32
	bpAddr                  uint64
	bpLen                   uint64
}

// bpfInsn is a single 8-byte BPF instruction.
// Matches struct bpf_insn from <linux/bpf.h>.
type bpfInsn struct {
	code   uint8  // opcode
	regs   uint8  // dst_reg (lower nibble) | src_reg (upper nibble)
	off    int16  // signed offset
	imm    int32  // signed immediate
}

// ─── ELF parsing ──────────────────────────────────────────────────────────────

// bpfElf holds the relevant contents extracted from a compiled BPF object.
type bpfElf struct {
	license    string
	mapDefs    map[string]bpfMapSpec // map name → spec (from ELF)
	progs      map[string][]bpfInsn  // section → instruction slice
	relaSecs   map[string][]bpfRela  // section → relocations
}

// bpfMapSpec is the map definition parsed from the ELF maps section.
type bpfMapSpec struct {
	mapType    uint32
	keySize    uint32
	valueSize  uint32
	maxEntries uint32
	flags      uint32
}

// bpfRela is a simplified RELA entry: the instruction index and the name of
// the map symbol being referenced.
type bpfRela struct {
	insnIdx uint64
	symName string
}

// parseBPFELF parses a pre-compiled BPF ELF object from r and returns the
// extracted programs, maps, relocations, and license. The BPF object must be
// a 64-bit little-endian ELF with standard BPF section conventions.
func parseBPFELF(r io.ReaderAt) (*bpfElf, error) {
	f, err := elf.NewFile(r)
	if err != nil {
		return nil, fmt.Errorf("parse ELF: %w", err)
	}
	defer f.Close()

	if f.Class != elf.ELFCLASS64 {
		return nil, fmt.Errorf("expected 64-bit ELF, got %v", f.Class)
	}
	if f.ByteOrder != binary.LittleEndian {
		return nil, fmt.Errorf("BPF objects must be little-endian (eBPF ABI)")
	}

	out := &bpfElf{
		mapDefs:  make(map[string]bpfMapSpec),
		progs:    make(map[string][]bpfInsn),
		relaSecs: make(map[string][]bpfRela),
	}

	// Load the symbol table once; it's referenced by relocation sections.
	syms, err := f.Symbols()
	if err != nil && !errors.Is(err, elf.ErrNoSymbols) {
		return nil, fmt.Errorf("read symbol table: %w", err)
	}

	for _, sec := range f.Sections {
		switch {
		case sec.Name == "license":
			b, err := sec.Data()
			if err != nil {
				return nil, fmt.Errorf("read license: %w", err)
			}
			out.license = strings.TrimRight(string(b), "\x00")

		case sec.Name == ".maps" || sec.Name == "maps":
			if err := parseMapsSection(f, sec, syms, out); err != nil {
				return nil, err
			}

		case strings.HasPrefix(sec.Name, "tracepoint/"):
			insns, err := readBPFInsns(sec)
			if err != nil {
				return nil, fmt.Errorf("read program %q: %w", sec.Name, err)
			}
			out.progs[sec.Name] = insns

		case sec.Type == elf.SHT_REL || sec.Type == elf.SHT_RELA:
			// Strip ".rel" or ".rela" prefix to get the target section name.
			target := strings.TrimPrefix(sec.Name, ".rela")
			target = strings.TrimPrefix(target, ".rel")
			if !strings.HasPrefix(target, "tracepoint/") {
				continue
			}
			relas, err := readRelas(f, sec, syms)
			if err != nil {
				return nil, fmt.Errorf("read relocations for %q: %w", sec.Name, err)
			}
			out.relaSecs[target] = relas
		}
	}

	if out.license == "" {
		out.license = "GPL" // fall back to most permissive default
	}

	return out, nil
}

// parseMapsSection reads map definitions from the BTF-style .maps ELF section.
// In BTF-defined maps each map is a global struct whose first five uint32
// fields encode: type, key_size, value_size, max_entries, map_flags.
func parseMapsSection(f *elf.File, sec *elf.Section, syms []elf.Symbol, out *bpfElf) error {
	data, err := sec.Data()
	if err != nil {
		return fmt.Errorf("read maps section: %w", err)
	}

	// Find the section index so we can match symbols.
	var secIdx elf.SectionIndex
	for i, s := range f.Sections {
		if s == sec {
			secIdx = elf.SectionIndex(i)
			break
		}
	}

	found := false
	for _, sym := range syms {
		if sym.Section != secIdx {
			continue
		}
		if elf.ST_TYPE(sym.Info) != elf.STT_OBJECT {
			continue
		}

		off := sym.Value
		size := sym.Size
		if size < 20 || int(off)+int(size) > len(data) {
			continue
		}

		mapData := data[off : off+size]
		out.mapDefs[sym.Name] = bpfMapSpec{
			mapType:    binary.LittleEndian.Uint32(mapData[0:4]),
			keySize:    binary.LittleEndian.Uint32(mapData[4:8]),
			valueSize:  binary.LittleEndian.Uint32(mapData[8:12]),
			maxEntries: binary.LittleEndian.Uint32(mapData[12:16]),
			flags:      binary.LittleEndian.Uint32(mapData[16:20]),
		}
		found = true
	}

	// Fall back: if we couldn't match symbols, parse the first map from the
	// raw section data (common for stripped BPF objects).
	if !found && len(data) >= 20 {
		out.mapDefs["execve_events"] = bpfMapSpec{
			mapType:    binary.LittleEndian.Uint32(data[0:4]),
			keySize:    binary.LittleEndian.Uint32(data[4:8]),
			valueSize:  binary.LittleEndian.Uint32(data[8:12]),
			maxEntries: binary.LittleEndian.Uint32(data[12:16]),
			flags:      binary.LittleEndian.Uint32(data[16:20]),
		}
	}

	return nil
}

// readBPFInsns reads BPF instructions from a program section.
// Instructions are 8 bytes each; the section data must be a multiple of 8 B.
func readBPFInsns(sec *elf.Section) ([]bpfInsn, error) {
	data, err := sec.Data()
	if err != nil {
		return nil, err
	}
	if len(data) == 0 {
		return nil, fmt.Errorf("empty program section %q", sec.Name)
	}
	if len(data)%8 != 0 {
		return nil, fmt.Errorf("section %q size %d not a multiple of 8", sec.Name, len(data))
	}

	insns := make([]bpfInsn, len(data)/8)
	r := bytes.NewReader(data)
	for i := range insns {
		if err := binary.Read(r, binary.LittleEndian, &insns[i]); err != nil {
			return nil, err
		}
	}
	return insns, nil
}

// readRelas reads relocation entries from a REL or RELA section, resolving
// each symbol index to its name using the provided symbol table.
func readRelas(f *elf.File, sec *elf.Section, syms []elf.Symbol) ([]bpfRela, error) {
	data, err := sec.Data()
	if err != nil {
		return nil, err
	}

	var relas []bpfRela

	switch sec.Type {
	case elf.SHT_RELA:
		const sz = 24 // sizeof(Elf64_Rela)
		if len(data)%sz != 0 {
			return nil, fmt.Errorf("RELA section size %d not a multiple of %d", len(data), sz)
		}
		r := bytes.NewReader(data)
		for r.Len() > 0 {
			var raw struct {
				Off    uint64
				Info   uint64
				Addend int64
			}
			if err := binary.Read(r, f.ByteOrder, &raw); err != nil {
				return nil, err
			}
			symIdx := raw.Info >> 32
			if int(symIdx) >= len(syms) {
				return nil, fmt.Errorf("symbol index %d out of range", symIdx)
			}
			relas = append(relas, bpfRela{
				insnIdx: raw.Off / 8,
				symName: syms[symIdx].Name,
			})
		}

	case elf.SHT_REL:
		const sz = 16 // sizeof(Elf64_Rel)
		if len(data)%sz != 0 {
			return nil, fmt.Errorf("REL section size %d not a multiple of %d", len(data), sz)
		}
		r := bytes.NewReader(data)
		for r.Len() > 0 {
			var raw struct {
				Off  uint64
				Info uint64
			}
			if err := binary.Read(r, f.ByteOrder, &raw); err != nil {
				return nil, err
			}
			symIdx := raw.Info >> 32
			if int(symIdx) >= len(syms) {
				return nil, fmt.Errorf("symbol index %d out of range", symIdx)
			}
			relas = append(relas, bpfRela{
				insnIdx: raw.Off / 8,
				symName: syms[symIdx].Name,
			})
		}
	}

	return relas, nil
}

// ─── BPF object loading ────────────────────────────────────────────────────────

// bpfObject holds the open file descriptors for a loaded BPF program set.
// Call Close to release all resources.
type bpfObject struct {
	mapFDs  map[string]int
	progFDs map[string]int
	perfFDs []int
	ringbuf *ringBufReader
}

// Close releases all file descriptors and the ring-buffer mmap.
func (o *bpfObject) Close() {
	if o.ringbuf != nil {
		o.ringbuf.close()
		o.ringbuf = nil
	}
	for _, fd := range o.perfFDs {
		_ = syscall.Close(fd)
	}
	for _, fd := range o.progFDs {
		_ = syscall.Close(fd)
	}
	for _, fd := range o.mapFDs {
		_ = syscall.Close(fd)
	}
}

// loadBPFObject parses the BPF ELF object from r, creates kernel maps, loads
// programs, attaches execve/execveat tracepoints, and returns a *bpfObject
// ready for ring-buffer consumption.
//
// Requires CAP_BPF (Linux ≥ 5.8) or CAP_SYS_ADMIN on older kernels.
func loadBPFObject(r io.ReaderAt) (*bpfObject, error) {
	parsed, err := parseBPFELF(r)
	if err != nil {
		return nil, fmt.Errorf("parse BPF ELF: %w", err)
	}
	if len(parsed.progs) == 0 {
		return nil, errors.New("BPF object contains no tracepoint programs")
	}

	obj := &bpfObject{
		mapFDs:  make(map[string]int),
		progFDs: make(map[string]int),
	}

	// ── 1. Create kernel BPF maps ─────────────────────────────────────────────

	rbMaxEntries := uint32(1 << 24) // 16 MiB default
	for name, spec := range parsed.mapDefs {
		fd, err := createBPFMap(spec)
		if err != nil {
			obj.Close()
			return nil, fmt.Errorf("BPF map create %q: %w (requires CAP_BPF)", name, err)
		}
		obj.mapFDs[name] = fd
		if name == "execve_events" && spec.maxEntries > 0 {
			rbMaxEntries = spec.maxEntries
		}
	}

	// Ensure the ring-buffer map exists (in case the maps section was empty).
	if _, ok := obj.mapFDs["execve_events"]; !ok {
		spec := bpfMapSpec{
			mapType:    bpfMapTypeRingBuf,
			maxEntries: rbMaxEntries,
		}
		fd, err := createBPFMap(spec)
		if err != nil {
			obj.Close()
			return nil, fmt.Errorf("create execve_events ring buffer: %w (requires CAP_BPF)", err)
		}
		obj.mapFDs["execve_events"] = fd
	}

	// ── 2. Load BPF programs ──────────────────────────────────────────────────

	licenseBytes := append([]byte(parsed.license), 0) // NUL-terminate

	for secName, insns := range parsed.progs {
		// Apply map-fd relocations before loading.
		if relas, ok := parsed.relaSecs[secName]; ok {
			if err := applyMapRelocations(insns, relas, obj.mapFDs); err != nil {
				obj.Close()
				return nil, fmt.Errorf("relocate %q: %w", secName, err)
			}
		}

		// Verifier log buffer (useful for debugging load failures).
		logBuf := make([]byte, 256*1024)

		attr := bpfProgLoadAttr{
			progType: bpfProgTypeTracepoint,
			insnCnt:  uint32(len(insns)),
			insns:    uint64(uintptr(unsafe.Pointer(&insns[0]))),
			license:  uint64(uintptr(unsafe.Pointer(&licenseBytes[0]))),
			logLevel: bpfLogLevel,
			logSize:  uint32(len(logBuf)),
			logBuf:   uint64(uintptr(unsafe.Pointer(&logBuf[0]))),
		}
		shortName := shortProgName(secName)
		copy(attr.progName[:], shortName)

		fd, err := bpfSyscall(bpfCmdProgLoad, unsafe.Pointer(&attr), unsafe.Sizeof(attr))
		// KeepAlive prevents the GC from collecting slices whose addresses
		// were stored as uint64 in attr (not tracked as GC roots).
		runtime.KeepAlive(insns)
		runtime.KeepAlive(licenseBytes)
		runtime.KeepAlive(logBuf)
		if err != nil {
			verifierLog := extractLog(logBuf)
			if verifierLog != "" {
				err = fmt.Errorf("%w; verifier log:\n%s", err, verifierLog)
			}
			obj.Close()
			return nil, fmt.Errorf("load BPF program %q: %w", secName, err)
		}
		obj.progFDs[secName] = fd
	}

	// ── 3. Attach tracepoints ─────────────────────────────────────────────────

	numCPU := runtime.NumCPU()
	for secName, progFD := range obj.progFDs {
		// Section format: "tracepoint/<group>/<name>"
		parts := strings.SplitN(strings.TrimPrefix(secName, "tracepoint/"), "/", 2)
		if len(parts) != 2 {
			obj.Close()
			return nil, fmt.Errorf("cannot parse tracepoint group/name from section %q", secName)
		}
		tpGroup, tpName := parts[0], parts[1]

		tpID, err := readTracepointID(tpGroup, tpName)
		if err != nil {
			obj.Close()
			return nil, fmt.Errorf("tracepoint %s/%s: %w", tpGroup, tpName, err)
		}

		for cpu := 0; cpu < numCPU; cpu++ {
			attr := &perfEventAttr{
				eventType: perfTypeTracepoint,
				size:      uint32(unsafe.Sizeof(perfEventAttr{})),
				config:    uint64(tpID),
				bits:      1, // disabled=1
			}

			pfd, err := perfEventOpen(attr, -1 /* all tasks */, cpu, -1 /* no group */)
			if err != nil {
				obj.Close()
				return nil, fmt.Errorf("perf_event_open %s/%s cpu%d: %w", tpGroup, tpName, cpu, err)
			}
			obj.perfFDs = append(obj.perfFDs, pfd)

			if err := ioctlFd(pfd, perfEventIOCSetBPF, uintptr(progFD)); err != nil {
				obj.Close()
				return nil, fmt.Errorf("PERF_EVENT_IOC_SET_BPF %s/%s cpu%d: %w", tpGroup, tpName, cpu, err)
			}
			if err := ioctlFd(pfd, perfEventIOCEnable, 0); err != nil {
				obj.Close()
				return nil, fmt.Errorf("PERF_EVENT_IOC_ENABLE %s/%s cpu%d: %w", tpGroup, tpName, cpu, err)
			}
		}
	}

	// ── 4. Open ring-buffer reader ────────────────────────────────────────────

	rbFD := obj.mapFDs["execve_events"]
	rb, err := newRingBufReader(rbFD, rbMaxEntries)
	if err != nil {
		obj.Close()
		return nil, fmt.Errorf("ring buffer reader: %w", err)
	}
	obj.ringbuf = rb

	return obj, nil
}

// createBPFMap calls BPF_MAP_CREATE and returns the resulting file descriptor.
func createBPFMap(spec bpfMapSpec) (int, error) {
	attr := bpfMapCreateAttr{
		mapType:    spec.mapType,
		keySize:    spec.keySize,
		valueSize:  spec.valueSize,
		maxEntries: spec.maxEntries,
		mapFlags:   spec.flags,
	}
	return bpfSyscall(bpfCmdMapCreate, unsafe.Pointer(&attr), unsafe.Sizeof(attr))
}

// applyMapRelocations patches the imm field of LD_IMM64 instructions that
// reference BPF maps, replacing the placeholder with the real kernel fd.
func applyMapRelocations(insns []bpfInsn, relas []bpfRela, mapFDs map[string]int) error {
	for _, rel := range relas {
		fd, ok := mapFDs[rel.symName]
		if !ok {
			return fmt.Errorf("no fd for map %q", rel.symName)
		}
		idx := int(rel.insnIdx)
		if idx >= len(insns) {
			return fmt.Errorf("relocation instruction index %d out of range (len=%d)", idx, len(insns))
		}
		ins := &insns[idx]
		if ins.code != bpfOpLdImm64 {
			return fmt.Errorf("insn[%d]: expected LD_IMM64 (0x%02x), got 0x%02x",
				idx, bpfOpLdImm64, ins.code)
		}
		// Set src_reg = BPF_PSEUDO_MAP_FD in the upper nibble of regs byte.
		ins.regs = (ins.regs & 0x0F) | (bpfPseudoMapFD << 4)
		ins.imm = int32(fd)
		// The second instruction of the LD_IMM64 pair carries the upper 32
		// bits of the immediate; for a 32-bit fd they are always 0.
		if idx+1 < len(insns) {
			insns[idx+1].imm = 0
		}
	}
	return nil
}

// readTracepointID reads the kernel-assigned numeric ID for a tracepoint.
// The ID is exposed at:
//
//	/sys/kernel/debug/tracing/events/<group>/<name>/id
func readTracepointID(group, name string) (uint32, error) {
	idPath := filepath.Join(tracepointIDDir, group, name, "id")
	b, err := os.ReadFile(idPath)
	if err != nil {
		return 0, fmt.Errorf("read %s: %w (debugfs/tracefs must be mounted)", idPath, err)
	}
	var id uint32
	if _, err := fmt.Sscan(strings.TrimSpace(string(b)), &id); err != nil {
		return 0, fmt.Errorf("parse tracepoint id from %q: %w", string(b), err)
	}
	return id, nil
}

// shortProgName derives a ≤15-character program name from an ELF section name.
// e.g. "tracepoint/syscalls/sys_enter_execve" → "trace_execve" (truncated).
func shortProgName(secName string) string {
	parts := strings.Split(secName, "/")
	name := parts[len(parts)-1]
	if len(name) > 15 {
		name = name[:15]
	}
	return name
}

// extractLog trims a NUL-padded verifier log buffer and returns the log text.
func extractLog(buf []byte) string {
	if i := bytes.IndexByte(buf, 0); i >= 0 {
		buf = buf[:i]
	}
	return strings.TrimSpace(string(buf))
}

// ─── Ring-buffer reader ────────────────────────────────────────────────────────
//
// The BPF ring buffer (BPF_MAP_TYPE_RINGBUF) exposes a memory-mapped region:
//
//	Offset 0:          consumer page — userspace writes consumer_pos here
//	Offset PAGE_SIZE:  producer page — kernel writes producer_pos here (r/o)
//	Offset 2*PAGE_SIZE: data pages  — circular record store (r/o)
//
// Each record:
//   struct bpf_ringbuf_hdr { u32 len; u32 pg_off; }
//   bit 31 of len = BUSY  (kernel is still filling the record — spin)
//   bit 30 of len = DISCARD (kernel chose to discard — skip)
//   bits 29:0    = actual data length in bytes
//
// After reading, userspace advances consumer_pos by:
//   sizeof(header) + roundUp(dataLen, 8)

// ringBufReader holds the mmap state for a BPF ring-buffer map.
type ringBufReader struct {
	ctrlMmap []byte   // consumer+producer pages (r/w for consumer, r/o for producer)
	dataMmap []byte   // circular data area
	mask     uint64   // dataSize − 1 (power-of-two mask for wrap-around)
	closeCh  chan struct{}
}

// consumerPos returns a pointer to the consumer position stored in the first
// control page (writable by userspace).
func (rb *ringBufReader) consumerPos() *uint64 {
	return (*uint64)(unsafe.Pointer(&rb.ctrlMmap[0]))
}

// producerPos returns a pointer to the producer position stored in the second
// control page (read-only for userspace).
func (rb *ringBufReader) producerPos() *uint64 {
	return (*uint64)(unsafe.Pointer(&rb.ctrlMmap[os.Getpagesize()]))
}

// newRingBufReader mmaps the ring-buffer associated with mapFD. dataSize is
// the max_entries value from the map definition (bytes, power-of-two multiple
// of PAGE_SIZE).
func newRingBufReader(mapFD int, dataSize uint32) (*ringBufReader, error) {
	pageSize := os.Getpagesize()
	ctrlSize := 2 * pageSize

	// Validate: dataSize must be a power of two and at least one page.
	if dataSize == 0 || dataSize&(dataSize-1) != 0 {
		return nil, fmt.Errorf("ring buffer max_entries %d is not a power of two", dataSize)
	}

	// Map the control pages (consumer r/w, producer r/o).
	// The kernel maps both control pages with the same fd at offset 0.
	ctrlMmap, err := syscall.Mmap(
		mapFD,
		0,
		ctrlSize,
		syscall.PROT_READ|syscall.PROT_WRITE,
		syscall.MAP_SHARED,
	)
	if err != nil {
		return nil, fmt.Errorf("mmap control pages: %w", err)
	}

	// Map the data pages (read-only, at offset 2*PAGE_SIZE in the kernel's
	// internal layout, but offset ctrlSize in the fd's mmap space).
	dataMmap, err := syscall.Mmap(
		mapFD,
		int64(ctrlSize),
		int(dataSize),
		syscall.PROT_READ,
		syscall.MAP_SHARED,
	)
	if err != nil {
		_ = syscall.Munmap(ctrlMmap)
		return nil, fmt.Errorf("mmap data pages: %w", err)
	}

	return &ringBufReader{
		ctrlMmap: ctrlMmap,
		dataMmap: dataMmap,
		mask:     uint64(dataSize - 1),
		closeCh:  make(chan struct{}),
	}, nil
}

// readSample blocks until a non-discarded ring-buffer record is available,
// then returns a copy of the record's data payload. It returns an error if
// ctx is cancelled or the reader is closed via close().
func (rb *ringBufReader) readSample(ctx context.Context) ([]byte, error) {
	const pollInterval = 250 * time.Microsecond

	for {
		cons := atomic.LoadUint64(rb.consumerPos())
		prod := atomic.LoadUint64(rb.producerPos())

		if cons == prod {
			// No records available; wait briefly before retrying.
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-rb.closeCh:
				return nil, errors.New("ring buffer reader closed")
			case <-time.After(pollInterval):
				continue
			}
		}

		// A record may be present. Read its header.
		off := cons & rb.mask
		if off+uint64(bpfRingBufHdrSize) > uint64(len(rb.dataMmap)) {
			// Header wraps; advance consumer to next alignment (should not happen
			// with power-of-two ring buffers that the kernel guarantees, but be safe).
			atomic.StoreUint64(rb.consumerPos(), cons+uint64(bpfRingBufHdrSize))
			continue
		}

		rawLen := atomic.LoadUint32((*uint32)(unsafe.Pointer(&rb.dataMmap[off])))

		if rawLen&bpfRingBufBusyBit != 0 {
			// Kernel is still writing this record; spin-wait briefly.
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-rb.closeCh:
				return nil, errors.New("ring buffer reader closed")
			case <-time.After(1 * time.Microsecond):
				continue
			}
		}

		dataLen := rawLen &^ (bpfRingBufBusyBit | bpfRingBufDiscardBit)
		discard := rawLen&bpfRingBufDiscardBit != 0

		// Advance the consumer position past this record.
		advance := uint64(bpfRingBufHdrSize) + uint64(alignUp(dataLen, 8))
		atomic.StoreUint64(rb.consumerPos(), cons+advance)

		if discard {
			continue
		}

		// Copy the payload, handling ring-buffer wrap-around.
		payload := make([]byte, dataLen)
		dataOff := (off + uint64(bpfRingBufHdrSize)) & rb.mask
		size := uint64(dataLen)

		if dataOff+size <= uint64(len(rb.dataMmap)) {
			copy(payload, rb.dataMmap[dataOff:dataOff+size])
		} else {
			// Wrap: copy in two parts.
			first := uint64(len(rb.dataMmap)) - dataOff
			copy(payload, rb.dataMmap[dataOff:])
			copy(payload[first:], rb.dataMmap[:size-first])
		}

		return payload, nil
	}
}

// close signals readSample to return and releases all mmap regions.
func (rb *ringBufReader) close() {
	select {
	case <-rb.closeCh:
		// Already closed.
	default:
		close(rb.closeCh)
	}
	_ = syscall.Munmap(rb.dataMmap)
	_ = syscall.Munmap(rb.ctrlMmap)
}

// alignUp rounds n up to the nearest multiple of align (which must be a
// power of two).
func alignUp(n, align uint32) uint32 {
	return (n + align - 1) &^ (align - 1)
}
