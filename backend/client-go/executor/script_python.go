package executor

import (
	"bytes"
	"client-go/config"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

// The Server owns SCRIPT_METADATA parsing and schema validation; the Client
// receives the resolved parameters and modes in the Control payload.
// The external interpreter receives plain Python globals only (no Client SDK).
const externalPythonBootstrap = `import json, sys
payload = json.load(sys.stdin.buffer)
kwargs = payload["params"]
ns = {"__name__": "__main__", "kwargs": kwargs}
ns.update(kwargs)
try:
    exec(compile(payload["source"], "<rch-script>", "exec"), ns)
except SystemExit as exc:
    print("Script terminated via SystemExit: " + str(exc), file=sys.stderr)
    sys.exit(1)
`

type externalPythonScriptPayload struct {
	Source string                 `json:"source"`
	Params map[string]interface{} `json:"params"`
}

func findExternalPython() (string, error) { return findExternalPythonWithConfig(config.Runtime()) }

func findExternalPythonWithConfig(settings *config.RuntimeStore) (string, error) {
	if configured := settings.PythonPath(); configured != "" {
		path, err := exec.LookPath(configured)
		if err != nil {
			return "", fmt.Errorf("configured Python interpreter %q is unavailable: %w", configured, err)
		}
		return path, nil
	}
	candidates := []string{"python3", "python"}
	if runtime.GOOS == "windows" {
		candidates = []string{"python", "python3"}
	}
	for _, name := range candidates {
		if executable, err := exec.LookPath(name); err == nil {
			return executable, nil
		}
	}
	return "", fmt.Errorf("Python interpreter not found (tried %s)", strings.Join(candidates, ", "))
}

// scriptRunResult retains the explicit terminal reason across the Control boundary.
type scriptRunResult struct {
	Status int
	Text   string
	Reason string
}

func runExternalPythonScriptMode(ctx context.Context, session *Session, source interface{}, extra interface{}, emit func(int, string), settings *config.RuntimeStore, outputMode string) scriptRunResult {
	if outputMode != config.ScriptCollect && outputMode != config.ScriptStream {
		return scriptRunResult{Status: 0, Text: "Invalid Script output_mode"}
	}
	code, ok := source.(string)
	if !ok || strings.TrimSpace(code) == "" {
		return scriptRunResult{Status: 0, Text: "Invalid script source"}
	}
	params := map[string]interface{}{}
	if extra != nil {
		data, valid := extra.(map[string]interface{})
		if !valid {
			return scriptRunResult{Status: 0, Text: "Invalid script parameters: extra must be an object"}
		}
		params = data
	}
	payload, err := json.Marshal(externalPythonScriptPayload{Source: code, Params: params})
	if err != nil {
		return scriptRunResult{Status: 0, Text: fmt.Sprintf("Invalid script parameters: %v", err)}
	}
	python, err := findExternalPythonWithConfig(settings)
	if err != nil {
		return scriptRunResult{Status: 0, Text: err.Error()}
	}
	seconds := settings.Seconds("SCRIPT_DEFAULT_TIMEOUT")
	ctx, cancel := context.WithTimeout(ctx, time.Duration(seconds)*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, python, "-u", "-c", externalPythonBootstrap)
	cmd.Dir = session.Cwd
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8")
	cmd.Stdin = bytes.NewReader(payload)
	configureShellCancellation(cmd)
	cmd.WaitDelay = 2 * time.Second
	// stderr is ordinary output; only the actual process exit determines status.
	// Sharing a single writer preserves order and lets os/exec serialize writes.
	var collected bytes.Buffer
	writer := &streamOutputWriter{status: 1, emit: emit}
	if outputMode == config.ScriptCollect {
		cmd.Stdout, cmd.Stderr = &collected, &collected
	} else {
		cmd.Stdout, cmd.Stderr = writer, writer
	}
	err = cmd.Run()
	writer.Flush()
	finish := func(status int, message, reason string) scriptRunResult {
		if outputMode == config.ScriptCollect {
			if status == 1 {
				return scriptRunResult{Status: status, Text: collected.String(), Reason: reason}
			}
			text := collected.String()
			if text != "" && !strings.HasSuffix(text, "\n") {
				text += "\n"
			}
			return scriptRunResult{Status: status, Text: text + message, Reason: reason}
		}
		return scriptRunResult{Status: status, Text: message, Reason: reason}
	}
	if ctx.Err() == context.DeadlineExceeded {
		return finish(0, fmt.Sprintf("Script timed out after %d seconds", seconds), "timed_out")
	}
	if ctx.Err() == context.Canceled {
		return finish(0, "Script cancelled", "cancelled")
	}
	if err == nil {
		return finish(1, "Script execution completed", "")
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return finish(0, fmt.Sprintf("Script exited with code %d", exitErr.ExitCode()), "")
	}
	return finish(0, fmt.Sprintf("Failed to execute script: %v", err), "")
}
