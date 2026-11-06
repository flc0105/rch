package executor

import (
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"
)

func TestDetachedCommandManifest(t *testing.T) {
	spec, ok := LookupCommand("run_detached")
	if !ok || !spec.Suggest || spec.Group != "execution" || spec.CancelPolicy != "none" || spec.Runner == nil {
		t.Fatalf("unexpected detached command registration: %#v, %v", spec, ok)
	}
}

func TestParseDetachedArguments(t *testing.T) {
	cases := []struct {
		raw     string
		windows bool
		want    []string
	}{
		{"", false, nil},
		{`./my\ tool --name "hello world" ''`, false, []string{"./my tool", "--name", "hello world", ""}},
		{`"/tmp/my binary" 'one two'`, false, []string{"/tmp/my binary", "one two"}},
		{`"C:\Program Files\App\runner.exe" --path "C:\Users\Me\a b.txt"`, true, []string{`C:\Program Files\App\runner.exe`, "--path", `C:\Users\Me\a b.txt`}},
		{`foo --arg 'a&b'`, false, []string{"foo", "--arg", "a&b"}},
	}
	for _, tc := range cases {
		got, err := parseDetachedArguments(tc.raw, tc.windows)
		if err != nil || !reflect.DeepEqual(got, tc.want) {
			t.Fatalf("parse(%q, windows=%v): %#v, %v; want %#v", tc.raw, tc.windows, got, err, tc.want)
		}
	}
	if _, err := parseDetachedArguments(`"unfinished`, false); err == nil {
		t.Fatal("unterminated quote accepted")
	}
}

func TestDetachedCommandDoesNotInterpretShellSyntax(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX process smoke test")
	}
	dir := t.TempDir()
	script := filepath.Join(dir, "command tool")
	marker := filepath.Join(dir, "marker.txt")
	scriptContent := "#!/bin/sh\nprintf '%s' \"$1\" > \"$2\"\n"
	if err := os.WriteFile(script, []byte(scriptContent), 0755); err != nil {
		t.Fatal(err)
	}
	sess := &Session{Cwd: dir}
	input := `run_detached "command tool" 'literal;touch-not-run' marker.txt`
	// The executable is found in the session directory; shell tokens are literal.
	status, response := sess.Dispatch(1, input)
	if status != 1 || !strings.Contains(response, "PID: ") {
		t.Fatalf("status %d output %q", status, response)
	}
	for i := 0; i < 100; i++ {
		contents, err := os.ReadFile(marker)
		if err == nil {
			if string(contents) != "literal;touch-not-run" {
				t.Fatalf("shell metacharacter changed: %q", contents)
			}
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("detached program did not run")
}

func TestDetachedStartFailure(t *testing.T) {
	status, response := cmdRunDetached(nil, &Session{Cwd: t.TempDir()}, "not-a-real-rch-executable-name-9999", nil)
	if status != 0 || !strings.Contains(response, "Failed to start detached process") {
		t.Fatalf("status=%d response=%q", status, response)
	}
}
