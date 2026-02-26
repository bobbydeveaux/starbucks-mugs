//go:build ignore

// gen.go generates the raw FileDescriptorProto bytes needed for proto/alert.pb.go.
// Run with: go run ./internal/proto/gen/gen.go
package main

import (
	"bytes"
	"compress/gzip"
	"fmt"
	"os"

	"google.golang.org/protobuf/proto"
	descriptorpb "google.golang.org/protobuf/types/descriptorpb"
)

func main() {
	b := ptr[bool]
	s := ptr[string]
	_ = b
	_ = s

	fd := &descriptorpb.FileDescriptorProto{
		Name:    s("proto/alert.proto"),
		Package: s("alert"),
		Options: &descriptorpb.FileOptions{
			GoPackage: s("github.com/tripwire/agent/proto"),
		},
		Syntax: s("proto3"),
		MessageType: []*descriptorpb.DescriptorProto{
			{
				Name: s("AgentRegistration"),
				Field: []*descriptorpb.FieldDescriptorProto{
					{Name: s("agent_cn"), Number: p(1), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_STRING.Enum(), JsonName: s("agentCn")},
					{Name: s("hostname"), Number: p(2), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_STRING.Enum(), JsonName: s("hostname")},
					{Name: s("platform"), Number: p(3), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_STRING.Enum(), JsonName: s("platform")},
					{Name: s("agent_version"), Number: p(4), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_STRING.Enum(), JsonName: s("agentVersion")},
					{Name: s("ip_address"), Number: p(5), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_STRING.Enum(), JsonName: s("ipAddress")},
				},
			},
			{
				Name: s("AgentEvent"),
				Field: []*descriptorpb.FieldDescriptorProto{
					{Name: s("host_id"), Number: p(1), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_STRING.Enum(), JsonName: s("hostId")},
					{Name: s("timestamp_ms"), Number: p(2), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_INT64.Enum(), JsonName: s("timestampMs")},
					{Name: s("tripwire_type"), Number: p(3), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_STRING.Enum(), JsonName: s("tripwireType")},
					{Name: s("rule_name"), Number: p(4), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_STRING.Enum(), JsonName: s("ruleName")},
					{Name: s("severity"), Number: p(5), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_STRING.Enum(), JsonName: s("severity")},
					{Name: s("event_detail"), Number: p(6), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_BYTES.Enum(), JsonName: s("eventDetail")},
				},
			},
			{
				Name: s("ServerAck"),
				Field: []*descriptorpb.FieldDescriptorProto{
					{Name: s("ok"), Number: p(1), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_BOOL.Enum(), JsonName: s("ok")},
					{Name: s("alert_id"), Number: p(2), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_STRING.Enum(), JsonName: s("alertId")},
					{Name: s("error"), Number: p(3), Label: descriptorpb.FieldDescriptorProto_LABEL_OPTIONAL.Enum(), Type: descriptorpb.FieldDescriptorProto_TYPE_STRING.Enum(), JsonName: s("error")},
				},
			},
		},
		Service: []*descriptorpb.ServiceDescriptorProto{
			{
				Name: s("AlertService"),
				Method: []*descriptorpb.MethodDescriptorProto{
					{
						Name:       s("RegisterAgent"),
						InputType:  s(".alert.AgentRegistration"),
						OutputType: s(".alert.ServerAck"),
					},
					{
						Name:            s("StreamAlerts"),
						InputType:       s(".alert.AgentEvent"),
						OutputType:      s(".alert.ServerAck"),
						ClientStreaming: b(true),
						ServerStreaming: b(true),
					},
				},
			},
		},
	}

	raw, err := proto.Marshal(fd)
	if err != nil {
		fmt.Fprintf(os.Stderr, "marshal error: %v\n", err)
		os.Exit(1)
	}

	var buf bytes.Buffer
	w := gzip.NewWriter(&buf)
	if _, err := w.Write(raw); err != nil {
		fmt.Fprintf(os.Stderr, "gzip write error: %v\n", err)
		os.Exit(1)
	}
	if err := w.Close(); err != nil {
		fmt.Fprintf(os.Stderr, "gzip close error: %v\n", err)
		os.Exit(1)
	}

	gzBytes := buf.Bytes()
	fmt.Printf("// Raw: %d bytes, GZip: %d bytes\n", len(raw), len(gzBytes))
	fmt.Printf("var file_proto_alert_proto_rawDescGZIP_once sync.Once\n")
	fmt.Printf("var file_proto_alert_proto_rawDescGZIP_data []byte\n\n")
	fmt.Printf("var file_proto_alert_proto_rawDesc = []byte{\n\t")
	for i, b := range gzBytes {
		if i > 0 && i%16 == 0 {
			fmt.Printf("\n\t")
		}
		fmt.Printf("0x%02x,", b)
	}
	fmt.Printf("\n}\n")
}

func ptr[T any](v T) *T { return &v }
func s(v string) *string { return &v }
func p(v int32) *int32   { return &v }
func b(v bool) *bool     { return &v }
