// Package alert contains the protobuf-generated Go bindings for the TripWire
// AlertService gRPC interface.
//
// To regenerate the Go source files from proto/alert.proto, use either:
//
//  1. From the repository root (recommended):
//
//     make proto
//
//  2. Via go generate (run from the repository root):
//
//     go generate ./proto/...
//
// Requires protoc, protoc-gen-go, and protoc-gen-go-grpc on PATH:
//
//	go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
//	go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
//
//go:generate protoc --go_out=. --go_opt=paths=source_relative --go-grpc_out=. --go-grpc_opt=paths=source_relative alert.proto
package alert
