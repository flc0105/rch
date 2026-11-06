package executor

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

var _ = Register(
	"run_detached", Usage("run_detached <program> [args...]"),
	Help("Start an independent program in a new session"),
	Group("execution"), Suggest(), CancelPolicy("none"), CommandRunner(cmdRunDetached),
)

func cmdRunDetached(_ context.Context, s *Session, raw string, _ func(int, string)) (int, string) {
	argv, err := parseDetachedArguments(raw, runtime.GOOS == "windows")
	if err != nil {
		return 0, fmt.Sprintf("Invalid arguments: %v", err)
	}
	if len(argv) == 0 {
		return 0, "Usage: run_detached <program> [args...]"
	}
	cmd, err := newDetachedProgramCommand(argv, s.Cwd)
	if err != nil {
		return 0, fmt.Sprintf("Failed to start detached process: %v", err)
	}
	if err := cmd.Start(); err != nil {
		return 0, fmt.Sprintf("Failed to start detached process: %v", err)
	}
	pid := cmd.Process.Pid
	// A detached subprocess must still be reaped while this client is alive.
	go func() { _ = cmd.Wait() }()
	return 1, fmt.Sprintf("Detached process started\nPID: %d\nCommand: %s", pid, strings.TrimSpace(raw))
}

func newDetachedProgramCommand(argv []string, cwd string) (*exec.Cmd, error) {
	if len(argv) == 0 {
		return nil, fmt.Errorf("program is required")
	}
	program := argv[0]
	if !filepath.IsAbs(program) {
		local := filepath.Join(cwd, program)
		if filepath.Dir(program) != "." || strings.HasPrefix(program, ".") {
			// Relative paths must resolve against the session's cwd, not the
			// Go Client's original process working directory.
			program = local
		} else if info, err := os.Stat(local); err == nil && !info.IsDir() {
			// Match Python: run a bare filename from cwd when it is not in PATH.
			program = local
		}
	}
	cmd := exec.Command(program, argv[1:]...)
	cmd.Dir = cwd
	cmd.Stdin, cmd.Stdout, cmd.Stderr = nil, nil, nil
	configureDetachedSpawn(cmd)
	return cmd, nil
}

// parseDetachedArguments recognizes quoted program paths and arguments without
// invoking a shell. On Windows backslashes remain literal path characters.
func parseDetachedArguments(raw string, windows bool) ([]string, error) {
	var args []string
	var token strings.Builder
	var quote rune
	started := false
	chars := []rune(raw)
	for i := 0; i < len(chars); i++ {
		c := chars[i]
		if quote == 0 && (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
			if started {
				args = append(args, token.String())
				token.Reset()
				started = false
			}
			continue
		}
		if c == '\\' && !windows && (quote == 0 || quote == '"') && i+1 < len(chars) {
			i++
			token.WriteRune(chars[i])
			started = true
			continue
		}
		if (c == '\'' || c == '"') && (quote == 0 || quote == c) {
			if quote == 0 {
				quote = c
			} else {
				quote = 0
			}
			started = true
			continue
		}
		token.WriteRune(c)
		started = true
	}
	if quote != 0 {
		return nil, fmt.Errorf("unterminated quote")
	}
	if started {
		args = append(args, token.String())
	}
	return args, nil
}
