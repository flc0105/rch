package executor

import (
	"strings"
	"testing"
)

func TestStreamOutputPreservesSplitUTF8(t *testing.T) {
	var chunks []string
	writer := &streamOutputWriter{status: 1, emit: func(_ int, s string) { chunks = append(chunks, s) }}
	data := []byte("中文\n")
	for _, ch := range data {
		_, _ = writer.Write([]byte{ch})
	}
	writer.Flush()
	if got := strings.Join(chunks, ""); got != "中文" {
		t.Fatalf("got %q", got)
	}
}

func TestShellCommandsInManifest(t *testing.T) {
	names := map[string]bool{}
	for _, item := range CommandManifest() {
		manifest, ok := item.(map[string]interface{})
		if !ok {
			t.Fatalf("bad command manifest item %T", item)
		}
		names[manifest["name"].(string)] = true
	}
	if !names["shell"] || !names["shell_stream"] {
		t.Fatalf("shell commands absent from manifest: %#v", names)
	}
}
