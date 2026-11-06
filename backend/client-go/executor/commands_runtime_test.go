package executor

import (
	"client-go/config"
	"context"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
)

func TestRuntimeSetCommandQuotedWindowsPaths(t *testing.T) {
	store := config.NewRuntimeStore(filepath.Join(t.TempDir(), "settings.json"))
	commands := []string{
		`SCRIPT_PYTHON_PATH 'C:\Program Files\Python312\python.exe'`,
		`SCRIPT_PYTHON_PATH "C:\Program Files\Python312\python.exe"`,
		`SCRIPT_PYTHON_PATH 'C:\Program Files\John'"'"'s Python\python.exe'`,
	}
	expected := []string{
		`C:\Program Files\Python312\python.exe`,
		`C:\Program Files\Python312\python.exe`,
		`C:\Program Files\John's Python\python.exe`,
	}
	for i, command := range commands {
		status, msg := runtimeSetCommand(command, store)
		if status != 1 || store.PythonPath() != expected[i] {
			t.Fatalf("%q: %d %q, got %q", command, status, msg, store.PythonPath())
		}
	}
	status, msg := runtimeSetCommand(`SCRIPT_PYTHON_PATH ''`, store)
	if status != 1 || store.PythonPath() != "" {
		t.Fatalf("empty path: %d %q", status, msg)
	}
	status, msg = runtimeSetCommand("--json", store)
	if status != 1 {
		t.Fatal(msg)
	}
	var doc map[string]interface{}
	if err := json.Unmarshal([]byte(msg), &doc); err != nil {
		t.Fatal(err)
	}
	if len(doc["items"].([]interface{})) != 4 {
		t.Fatal("incorrect payload")
	}
	status, msg = runtimeSetCommand("COMMAND_DEFAULT_SHELL_TIMEOUT 12", store)
	if status != 1 || store.Seconds("COMMAND_DEFAULT_SHELL_TIMEOUT") != 12 {
		t.Fatalf("set: %d %s", status, msg)
	}
	status, msg = runtimeSetCommand("--reset COMMAND_DEFAULT_SHELL_TIMEOUT", store)
	if status != 1 || store.Seconds("COMMAND_DEFAULT_SHELL_TIMEOUT") != 30 {
		t.Fatalf("reset: %d %s", status, msg)
	}
}

func TestRuntimeSetCommandRejectsInvalidSyntax(t *testing.T) {
	store := config.NewRuntimeStore(filepath.Join(t.TempDir(), "settings.json"))
	for _, raw := range []string{`SCRIPT_PYTHON_PATH 'unclosed`, "COMMAND_DEFAULT_SHELL_TIMEOUT bad", "UNKNOWN_KEY 1", "SCRIPT_PYTHON_PATH a b", "--reset", "--json extra"} {
		status, _ := runtimeSetCommand(raw, store)
		if status != 0 {
			t.Errorf("accepted %q", raw)
		}
	}
	found := false
	for _, entry := range CommandManifest() {
		item := entry.(map[string]interface{})
		if item["name"] == "set" {
			found = true
			break
		}
	}
	if !found {
		t.Fatal("set command missing from manifest")
	}
	status, text := runtimeSetCommand("", store)
	if status != 1 || !strings.Contains(text, "SCRIPT_DEFAULT_TIMEOUT") {
		t.Fatal("list failed")
	}
}

func TestRuntimeSetDispatchJsonUsesBuiltin(t *testing.T) {
	session := &Session{Cwd: t.TempDir()}
	status, text := session.DispatchContext(context.Background(), 901, "set --json")
	if status != 1 {
		t.Fatalf("set --json dispatcher: %s", text)
	}
	var payload map[string]interface{}
	if err := json.Unmarshal([]byte(text), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload["items"].([]interface{})) != 4 {
		t.Fatal("unexpected configuration fields")
	}
}
