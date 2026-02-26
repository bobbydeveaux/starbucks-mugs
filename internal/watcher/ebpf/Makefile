# internal/watcher/ebpf/Makefile
#
# Compiles process.bpf.c into a BPF object file using clang.
# The resulting process.bpf.o is embedded into the Go binary via //go:embed
# in process.go so that no runtime compilation is required.
#
# Prerequisites (install once):
#   apt-get install -y clang llvm libbpf-dev linux-headers-$(uname -r)
#
# Generate vmlinux.h from the running kernel (needed for CO-RE):
#   bpftool btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h
#
# Then build:
#   make -C internal/watcher/ebpf

CLANG   ?= clang
LLVMST  ?= llvm-strip
ARCH    ?= x86
CFLAGS  := -O2 -g -Wall -Werror \
           -target bpf \
           -D__TARGET_ARCH_$(ARCH) \
           -I. \
           -I/usr/include/$(shell uname -m)-linux-gnu

.PHONY: all clean

all: process.bpf.o

process.bpf.o: process.bpf.c process.h vmlinux.h
	$(CLANG) $(CFLAGS) -c $< -o $@
	$(LLVMST) -g $@   # strip debug info; keep BTF

vmlinux.h:
	@echo "Generating vmlinux.h from running kernel BTF..."
	bpftool btf dump file /sys/kernel/btf/vmlinux format c > $@

clean:
	rm -f process.bpf.o vmlinux.h
