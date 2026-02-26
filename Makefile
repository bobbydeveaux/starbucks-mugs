# TripWire dashboard server — top-level Makefile
#
# Targets
#   proto      - regenerate Go bindings from proto/alert.proto
#   build      - compile the server binary
#   test       - run all unit tests
#   help       - print this help

.PHONY: proto build test help

## proto: Regenerate proto/alert.pb.go and proto/alert_grpc.pb.go
##        Requires protoc, protoc-gen-go, and protoc-gen-go-grpc on PATH.
##        Install plugins:
##          go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
##          go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
proto:
	protoc \
		--go_out=. \
		--go_opt=paths=source_relative \
		--go-grpc_out=. \
		--go-grpc_opt=paths=source_relative \
		proto/alert.proto

## build: Compile the tripwire server binary
build:
	go build -o tripwire-server ./cmd/server

## test: Run all unit tests
test:
	go test ./...

## help: Print available targets
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## //'
