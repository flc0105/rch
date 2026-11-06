//go:build !windows

package executor

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestRunDetachedReturnsActualProgramPIDAndSession(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "my executable")
	output := filepath.Join(dir, "pid.txt")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nprintf '%d' \"$$\" > \"$1\"\nsleep 1\n"), 0755); err != nil {
		t.Fatal(err)
	}
	sess := &Session{Cwd: dir}
	status, response := sess.Dispatch(10, `run_detached "my executable" pid.txt`)
	if status != 1 {
		t.Fatalf("%s", response)
	}
	parts := strings.SplitN(response, "PID: ", 2)
	if len(parts) != 2 {
		t.Fatalf("missing PID: %s", response)
	}
	pid, err := strconv.Atoi(strings.SplitN(parts[1], "\n", 2)[0])
	if err != nil {
		t.Fatal(err)
	}
	var actual int
	for i := 0; i < 100; i++ {
		contents, err := os.ReadFile(output)
		if err == nil {
			actual, _ = strconv.Atoi(string(contents))
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if actual != pid {
		t.Fatalf("reported PID %d vs launched executable PID %d", pid, actual)
	}
	sid, err := syscall.Getpgid(pid)
	if err != nil {
		t.Fatal(err)
	}
	if sid != pid {
		t.Fatalf("expected independent process group leader %d, got %d", pid, sid)
	}
}

func TestRelativeExecutableUsesSessionCwd(t *testing.T) {
	dir := t.TempDir()
	childDir := filepath.Join(dir, "bin")
	if err := os.Mkdir(childDir, 0755); err != nil {
		t.Fatal(err)
	}
	script := filepath.Join(childDir, "tool")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nsleep 0.2\n"), 0755); err != nil {
		t.Fatal(err)
	}
	cmd, err := newDetachedProgramCommand([]string{"./bin/tool"}, dir)
	if err != nil {
		t.Fatal(err)
	}
	if cmd.Path != script {
		t.Fatalf("cmd.Path=%q want %q", cmd.Path, script)
	}
}
