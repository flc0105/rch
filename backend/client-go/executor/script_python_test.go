package executor

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

func scriptTestSession(t *testing.T) *Session {
	t.Helper()
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	return &Session{Cwd: cwd}
}

func requirePython(t *testing.T) {
	t.Helper()
	if _, err := findExternalPython(); err != nil {
		t.Skip(err)
	}
}

func TestScriptExecSchemaValuesAndDirectGlobals(t *testing.T) {
	requirePython(t)
	params := map[string]interface{}{"target": "/tmp/中文 example", "limit": float64(4), "verbose": true, "__script_name__": "ops/check"}
	code := "" + `SCRIPT_METADATA = {"params": [{"name":"target","type":"string"}]}
import json
print(json.dumps({"target": kwargs["target"], "direct": target, "limit": limit, "verbose": verbose, "script": kwargs["__script_name__"]}, sort_keys=True))`
	var stdout, stderr []string
	status, final := RunExternalPythonScript(context.Background(), scriptTestSession(t), code, params, func(code int, text string) {
		if code == 1 {
			stdout = append(stdout, text)
		} else {
			stderr = append(stderr, text)
		}
	})
	if status != 1 || final != "Script execution completed" || len(stderr) != 0 {
		t.Fatalf("unexpected result: status=%d final=%q stderr=%#v", status, final, stderr)
	}
	got := strings.Join(stdout, "\n")
	var parsed map[string]interface{}
	if err := json.Unmarshal([]byte(got), &parsed); err != nil {
		t.Fatalf("invalid JSON from Python: %s: %v", got, err)
	}
	if parsed["direct"] != "/tmp/中文 example" || parsed["limit"] != float64(4) || parsed["script"] != "ops/check" {
		t.Fatalf("schema-bound arguments missing: %s", got)
	}
}

func TestScriptErrorAndInvalidPayload(t *testing.T) {
	for _, input := range []struct {
		source interface{}
		extra  interface{}
		needle string
	}{
		{"", nil, "Invalid script source"},
		{"print('ok')", []int{1}, "extra must be an object"},
		{"print('ok')", map[string]interface{}{"bad": make(chan int)}, "Invalid script parameters"},
	} {
		status, message := RunExternalPythonScript(context.Background(), scriptTestSession(t), input.source, input.extra, nil)
		if status != 0 || !strings.Contains(message, input.needle) {
			t.Fatalf("%#v: %d %q", input, status, message)
		}
	}
	requirePython(t)
	var emitted []string
	status, message := RunExternalPythonScript(context.Background(), scriptTestSession(t), "raise ValueError('bad input')", nil, func(_ int, s string) { emitted = append(emitted, s) })
	if status != 0 || !strings.Contains(message, "code") || !strings.Contains(strings.Join(emitted, " "), "bad input") {
		t.Fatalf("error lost: %d %q %#v", status, message, emitted)
	}
}

func TestScriptCancellationDoesNotBlock(t *testing.T) {
	requirePython(t)
	ctx, cancel := context.WithCancel(context.Background())
	session := scriptTestSession(t)
	finished := make(chan struct{})
	go func() {
		defer close(finished)
		time.AfterFunc(100*time.Millisecond, cancel)
		status, message := RunExternalPythonScript(ctx, session, "import time; time.sleep(30)", nil, nil)
		if status != 0 || message != "Script cancelled" {
			t.Errorf("cancel failure: %d %q", status, message)
		}
	}()
	select {
	case <-finished:
	case <-time.After(4 * time.Second):
		t.Fatal("cancellation did not terminate subprocess")
	}
}

func TestScriptInterpreterMissingReturnsError(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	status, message := RunExternalPythonScript(context.Background(), scriptTestSession(t), "print(1)", nil, nil)
	if status != 0 || !strings.Contains(message, "Python interpreter not found") {
		t.Fatalf("status=%d text=%q", status, message)
	}
}

func TestScriptSystemExitReportsFailure(t *testing.T) {
	requirePython(t)
	var output []string
	status, result := RunExternalPythonScript(context.Background(), scriptTestSession(t), "import sys; sys.exit(0)", nil, func(_ int, line string) { output = append(output, line) })
	if status != 0 || !strings.Contains(result, "code 1") || !strings.Contains(strings.Join(output, "\n"), "SystemExit") {
		t.Fatalf("SystemExit must fail: %d %q %#v", status, result, output)
	}
}
