package executor

import (
	"bytes"
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

const externalPythonScriptTimeout = 300 * time.Second

// The Server owns SCRIPT_METADATA parsing and schema validation; the Client
// receives the resulting parameters in the script message's extra field.
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

func findExternalPython() (string, error) {
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

// RunExternalPythonScript executes a Server script in an external Python
// process. stdout and stderr use the same interim-result protocol as shell_stream.
// The foreground task slot and cancellation belong to the Handler.
func RunExternalPythonScript(ctx context.Context, session *Session, source interface{}, extra interface{}, emit func(int, string)) (int, string) {
	code, ok := source.(string)
	if !ok || strings.TrimSpace(code) == "" {
		return 0, "Invalid script source"
	}
	params := map[string]interface{}{}
	if extra != nil {
		data, valid := extra.(map[string]interface{})
		if !valid {
			return 0, "Invalid script parameters: extra must be an object"
		}
		params = data
	}
	payload, err := json.Marshal(externalPythonScriptPayload{Source: code, Params: params})
	if err != nil {
		return 0, fmt.Sprintf("Invalid script parameters: %v", err)
	}
	python, err := findExternalPython()
	if err != nil {
		return 0, err.Error()
	}
	ctx, cancel := context.WithTimeout(ctx, externalPythonScriptTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, python, "-u", "-c", externalPythonBootstrap)
	cmd.Dir = session.Cwd
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8")
	cmd.Stdin = bytes.NewReader(payload)
	configureShellCancellation(cmd)
	stdout := &streamOutputWriter{status: 1, emit: emit}
	stderr := &streamOutputWriter{status: 0, emit: emit}
	cmd.Stdout, cmd.Stderr = stdout, stderr
	err = cmd.Run()
	stdout.Flush()
	stderr.Flush()
	if ctx.Err() == context.DeadlineExceeded {
		return 0, "Script timed out after 300 seconds"
	}
	if ctx.Err() == context.Canceled {
		return 0, "Script cancelled"
	}
	if err == nil {
		return 1, "Script execution completed"
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return 0, fmt.Sprintf("Script exited with code %d", exitErr.ExitCode())
	}
	return 0, fmt.Sprintf("Failed to execute script: %v", err)
}
