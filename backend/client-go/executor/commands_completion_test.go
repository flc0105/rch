package executor

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
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
		{"edit ", []string{"dir one", "dir two", "file one.txt"}},
		{"edit dir one/", []string{"dir one/child.txt"}},
		{"download dir one/", []string{"dir one/child.txt"}},
		{"unknown ", []string{}},
	}
	for _, tt := range cases {
		t.Run(tt.input, func(t *testing.T) {
			command := strings.Fields(tt.input)
			payload := map[string]interface{}{"raw_input": tt.input, "cursor_position": len(tt.input), "max_results": 0}
			if len(command) > 0 && command[0] == "edit" {
				payload["completion"] = map[string]interface{}{"provider": "filesystem", "kinds": []interface{}{"file", "directory"}}
			}
			result, err := CompleteCommandCompletion(s, payload)
			if err != nil {
				t.Fatal(err)
			}
			items := result["items"].([]interface{})
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

func TestCommandManifestCarriesMinimalCompletionSpec(t *testing.T) {
	manifest := CommandManifest()
	byName := map[string]map[string]interface{}{}
	for _, raw := range manifest {
		item := raw.(map[string]interface{})
		byName[item["name"].(string)] = item
	}
	cd := byName["cd"]["completion"].(map[string]interface{})
	if cd["provider"] != "filesystem" {
		t.Fatalf("cd provider: %#v", cd)
	}
	if got := cd["kinds"].([]string); len(got) != 1 || got[0] != "directory" {
		t.Fatalf("cd kinds: %#v", got)
	}
	download := byName["download"]["completion"].(map[string]interface{})
	if got := download["kinds"].([]string); len(got) != 2 || got[0] != "file" || got[1] != "directory" {
		t.Fatalf("download kinds: %#v", got)
	}
	if _, exists := byName["command_completions"]; exists {
		t.Fatal("legacy command_completions pseudo command remains in manifest")
	}
}

func TestCommandCompletionFiltersPrefixBeforeResultLimit(t *testing.T) {
	s := testFileSession(t)
	for i := 0; i < 70; i++ {
		name := fmt.Sprintf("aaa-%03d.txt", i)
		if err := os.WriteFile(filepath.Join(s.Cwd, name), []byte(""), 0644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(s.Cwd, "rchclient_go_loader.zip"), []byte("ok"), 0644); err != nil {
		t.Fatal(err)
	}
	result, err := CompleteCommandCompletion(s, map[string]interface{}{
		"raw_input": "download rchc", "cursor_position": len("download rchc"), "max_results": float64(50),
	})
	if err != nil {
		t.Fatal(err)
	}
	items := result["items"].([]interface{})
	if len(items) != 1 || items[0].(map[string]interface{})["candidatePath"] != "rchclient_go_loader.zip" {
		t.Fatalf("prefix filtering after truncation: %#v", items)
	}
}
