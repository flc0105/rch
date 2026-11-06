package executor

import (
	"context"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"client-go/config"
)

func TestScriptInterpreterOverrideAndTimeout(t *testing.T) {
	store := config.NewRuntimeStore(filepath.Join(t.TempDir(), "runtime.json"))
	if _, err := store.Set("SCRIPT_PYTHON_PATH", filepath.Join(t.TempDir(), "missing-python")); err != nil {
		t.Fatal(err)
	}
	status, output := runExternalPythonScriptWithConfig(context.Background(), scriptTestSession(t), "print('hello')", nil, nil, store)
	if status != 0 || !strings.Contains(output, "configured Python interpreter") {
		t.Fatalf("invalid path fell back: %d %q", status, output)
	}
	if err := store.Reset("SCRIPT_PYTHON_PATH"); err != nil {
		t.Fatal(err)
	}
	interpreter, err := findExternalPythonWithConfig(store)
	if err != nil {
		t.Skipf("Python not found: %v", err)
	}
	if _, err := store.Set("SCRIPT_PYTHON_PATH", interpreter); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Set("SCRIPT_DEFAULT_TIMEOUT", "1"); err != nil {
		t.Fatal(err)
	}
	started := time.Now()
	status, output = runExternalPythonScriptWithConfig(context.Background(), scriptTestSession(t), "import time; time.sleep(5)", nil, nil, store)
	if status != 0 || output != "Script timed out after 1 seconds" {
		t.Fatalf("timeout failed: %d %q", status, output)
	}
	if time.Since(started) > 4*time.Second {
		t.Fatal("timeout not enforced")
	}
}
