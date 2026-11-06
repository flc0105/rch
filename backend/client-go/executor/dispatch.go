package executor

import (
	"client-go/config"
	"context"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

func (s *Session) Dispatch(commandID int, raw string) (int, string) {
	return s.DispatchContext(context.Background(), commandID, raw)
}

func (s *Session) DispatchContext(ctx context.Context, commandID int, raw string) (int, string) {
	return s.DispatchContextOutput(ctx, commandID, raw, nil)
}

func (s *Session) DispatchContextOutput(ctx context.Context, commandID int, raw string, interim func(int, string)) (int, string) {
	s.CurrentCommandID = commandID
	defer func() { s.CurrentCommandID = 0 }()

	raw = strings.TrimSpace(raw)
	if raw == "" {
		return 0, "empty command"
	}

	name, args := parseCommand(raw)
	if spec, ok := LookupCommand(name); ok {
		if spec.Runner != nil {
			return spec.Runner(ctx, s, commandTail(raw), interim)
		}
		return spec.Handler(s, args)
	}

	return s.runShellContext(ctx, raw)
}

// commandTail preserves shell quoting and whitespace inside the command body.
func commandTail(raw string) string {
	raw = strings.TrimSpace(raw)
	end := strings.IndexAny(raw, " \t\r\n")
	if end < 0 {
		return ""
	}
	return strings.TrimSpace(raw[end:])
}

func parseCommand(raw string) (string, []string) {
	parts := strings.Fields(strings.TrimSpace(raw))
	if len(parts) == 0 {
		return "", nil
	}
	return strings.ToLower(parts[0]), parts[1:]
}

func (s *Session) runShellContext(ctx context.Context, command string) (int, string) {
	timedCtx, cancel := context.WithTimeout(ctx, time.Duration(config.Runtime().Seconds("COMMAND_DEFAULT_SHELL_TIMEOUT"))*time.Second)
	defer cancel()
	cmd := newShellCommand(timedCtx, command, s.Cwd)
	out, err := cmd.CombinedOutput()
	if timedCtx.Err() == context.DeadlineExceeded {
		return 0, "Command timed out"
	}
	if err != nil {
		if len(out) > 0 {
			return 0, string(out)
		}
		return 0, err.Error()
	}
	return 1, string(out)
}

func newShellCommand(ctx context.Context, command, cwd string) *exec.Cmd {
	var cmd *exec.Cmd
	if runtime.GOOS == "windows" {
		cmd = exec.CommandContext(ctx, "cmd", "/C", command)
	} else {
		cmd = exec.CommandContext(ctx, "sh", "-c", command)
	}

	configureShellCancellation(cmd)
	cmd.WaitDelay = 500 * time.Millisecond

	if strings.TrimSpace(cwd) != "" {
		cmd.Dir = cwd
	}

	return cmd
}
