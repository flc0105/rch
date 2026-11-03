package executor

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"strings"
	"unicode/utf8"
)

var (
	_ = Register(
		"shell", Usage("shell <command>"), Help("Run a shell command"),
		Group("execution"), Suggest(), CancelPolicy("process"), CommandRunner(cmdShell),
	)
	_ = Register(
		"shell_stream", Usage("shell_stream <command>"), Help("Run a command with live output"),
		Group("execution"), Suggest(), CancelPolicy("process"), Output("stream"), CommandRunner(cmdShellStream),
	)
)

func cmdShell(ctx context.Context, s *Session, command string, _ func(int, string)) (int, string) {
	if strings.TrimSpace(command) == "" {
		return 0, "Usage: shell <command>"
	}
	cmd := newShellCommand(ctx, command, s.Cwd)
	output, err := cmd.CombinedOutput()
	if ctx.Err() != nil {
		return 0, "Command cancelled"
	}
	if err == nil {
		return 1, string(output)
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		message := strings.TrimSpace(string(output))
		if message != "" {
			message += "\n"
		}
		return 0, fmt.Sprintf("%sCommand exited with code %d", message, exitErr.ExitCode())
	}
	return 0, fmt.Sprintf("Failed to execute command: %v", err)
}

func cmdShellStream(ctx context.Context, s *Session, command string, interim func(int, string)) (int, string) {
	if strings.TrimSpace(command) == "" {
		return 0, "Usage: shell_stream <command>"
	}
	cmd := newShellCommand(ctx, command, s.Cwd)
	stdout := &streamOutputWriter{status: 1, emit: interim}
	stderr := &streamOutputWriter{status: 0, emit: interim}
	cmd.Stdout, cmd.Stderr = stdout, stderr
	err := cmd.Run()
	stdout.Flush()
	stderr.Flush()
	if ctx.Err() != nil {
		return 0, "Command cancelled"
	}
	if err == nil {
		return 1, "Command completed"
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return 0, fmt.Sprintf("Command exited with code %d", exitErr.ExitCode())
	}
	return 0, fmt.Sprintf("Failed to execute command: %v", err)
}

// Output is streamed as text frames without losing UTF-8 characters split by pipe reads.
// The final result (eof=1) is sent by the command dispatcher after Run returns.
type streamOutputWriter struct {
	status  int
	emit    func(int, string)
	pending []byte
}

func (w *streamOutputWriter) Write(p []byte) (int, error) {
	w.pending = append(w.pending, p...)
	for {
		at := bytes.IndexByte(w.pending, '\n')
		if at < 0 {
			break
		}
		line := w.pending[:at]
		if utf8.Valid(line) {
			w.send(bytes.TrimSuffix(line, []byte{'\r'}))
			w.pending = w.pending[at+1:]
		} else {
			break
		}
	}
	// Allow long lines without an unbounded buffer, preserving UTF-8 boundaries.
	if len(w.pending) > 16384 {
		at := len(w.pending)
		for at > 0 && !utf8.Valid(w.pending[:at]) {
			at--
		}
		if at > 0 {
			w.send(w.pending[:at])
			w.pending = w.pending[at:]
		}
	}
	return len(p), nil
}

func (w *streamOutputWriter) Flush() {
	if len(w.pending) > 0 {
		w.send(bytes.TrimRight(w.pending, "\r\n"))
	}
	w.pending = nil
}

func (w *streamOutputWriter) send(b []byte) {
	if w.emit != nil {
		w.emit(w.status, string(b))
	}
}
