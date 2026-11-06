package executor

import (
	"os"
	"path/filepath"
	"testing"
)

func TestCommandCompletionsFilesDirectoriesAndPrefixes(t *testing.T) {
	s := testFileSession(t)
	if err := os.Mkdir(filepath.Join(s.Cwd, "dir one"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(s.Cwd, "dir two"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(s.Cwd, "file one.txt"), []byte("text"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(s.Cwd, "dir one", "child.txt"), []byte("ok"), 0644); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		input string
		names []string
	}{
		{"cd ", []string{"dir one", "dir two"}},
		{"download ", []string{"dir one", "dir two", "file one.txt"}},
		{"download dir one/", []string{"dir one/child.txt"}},
		{"unknown ", []string{}},
	}
	for _, tt := range cases {
		t.Run(tt.input, func(t *testing.T) {
			status, text := executeRemote(t, s, remoteCommand("command_completions", map[string]interface{}{"raw_input": tt.input, "cursor_position": len(tt.input), "max_results": 0}))
			if status != 1 {
				t.Fatal(text)
			}
			payload := decodeRemoteResult(t, text)
			items := payload["items"].([]interface{})
			if len(items) != len(tt.names) {
				t.Fatalf("items: %#v expected: %#v", items, tt.names)
			}
			for i, want := range tt.names {
				item := items[i].(map[string]interface{})
				if item["candidatePath"] != want {
					t.Errorf("got %v want %v", item["candidatePath"], want)
				}
				if _, ok := item["isDir"].(bool); !ok {
					t.Errorf("isDir missing: %#v", item)
				}
			}
		})
	}
}

func TestCompletionCursorByteOffsetPreservesUnicode(t *testing.T) {
	cases := []struct {
		text  string
		units int
		want  string
	}{
		{"download 文档/", 12, "download 文档/"},
		{"download 😀/", 11, "download 😀"},
		{"abc", 100, "abc"},
		{"abc", 0, ""},
	}
	for _, tt := range cases {
		got := tt.text[:completionCursorByteOffset(tt.text, tt.units)]
		if got != tt.want {
			t.Errorf("%q, units=%d: got %q want %q", tt.text, tt.units, got, tt.want)
		}
	}
}
