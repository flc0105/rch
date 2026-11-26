package executor

import (
	"client-go/config"
	"client-go/protocol"
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
	var doc []map[string]interface{}
	if err := json.Unmarshal([]byte(msg), &doc); err != nil {
		t.Fatal(err)
	}
	if len(doc) != 11 {
		t.Fatal("incorrect payload")
	}
	status, msg = runtimeSetCommand("COMMAND_DEFAULT_SHELL_TIMEOUT 12", store)
	if status != 1 || msg != "COMMAND_DEFAULT_SHELL_TIMEOUT updated: 30 → 12" || store.Seconds("COMMAND_DEFAULT_SHELL_TIMEOUT") != 12 {
		t.Fatalf("set: %d %s", status, msg)
	}
	status, msg = runtimeSetCommand("SCRIPT_DEFAULT_OUTPUT_MODE stream", store)
	if status != 1 || msg != "SCRIPT_DEFAULT_OUTPUT_MODE updated: 'collect' → 'stream'" {
		t.Fatalf("script mode: %d %s", status, msg)
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
	var payload []map[string]interface{}
	if err := json.Unmarshal([]byte(text), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload) != 11 {
		t.Fatal("unexpected configuration fields")
	}
}

func TestLegacySetSharesRuntimeStore(t *testing.T) {
	store := config.NewRuntimeStore(filepath.Join(t.TempDir(), "settings.json"))
	status, result := executeConfiguration(store, protocol.ConfigurationSet, map[string]interface{}{"key": config.ScriptOutputConfig, "value": config.ScriptStream})
	if status != 1 || store.Get(config.ScriptOutputConfig) != config.ScriptStream {
		t.Fatalf("set: %v %v", status, result)
	}
	status, _ = runtimeSetCommand("SCRIPT_DEFAULT_OUTPUT_MODE collect", store)
	if status != 1 || store.Get(config.ScriptOutputConfig) != config.ScriptCollect {
		t.Fatal("CLI store mismatch")
	}
	status, _ = executeConfiguration(store, protocol.ConfigurationSet, map[string]interface{}{"key": config.ScriptOutputConfig, "value": "invalid"})
	if status != 0 || store.Get(config.ScriptOutputConfig) != config.ScriptCollect {
		t.Fatal("invalid value accepted")
	}
	status, _ = executeConfiguration(store, protocol.ConfigurationSet, map[string]interface{}{"key": "COMMAND_DEFAULT_SHELL_TIMEOUT", "value": float64(12)})
	if status != 1 || store.Seconds("COMMAND_DEFAULT_SHELL_TIMEOUT") != 12 {
		t.Fatal("typed set failed")
	}
	status, _ = executeConfiguration(store, protocol.ConfigurationReset, map[string]interface{}{"key": "COMMAND_DEFAULT_SHELL_TIMEOUT"})
	if status != 1 || store.Seconds("COMMAND_DEFAULT_SHELL_TIMEOUT") != 30 {
		t.Fatal("reset failed")
	}
}

func TestLegacySetEnvelopeAndCLIViews(t *testing.T) {
	store := config.NewRuntimeStore(filepath.Join(t.TempDir(), "settings.json"))
	status, raw := executeConfiguration(store, protocol.ConfigurationGet, map[string]interface{}{})
	get := raw.(map[string]interface{})
	if status != 1 || get["status"] != "success" || get["message"] != "" {
		t.Fatalf("GET envelope: %v", raw)
	}
	payload := get["data"].(map[string]interface{})
	if _, found := payload["store_path"]; !found {
		t.Fatal("GET should retain full UI schema")
	}
	if _, found := payload["items"]; !found {
		t.Fatal("GET missing configuration items")
	}
	status, raw = executeConfiguration(store, protocol.ConfigurationSet, map[string]interface{}{
		"key": config.ScriptOutputConfig, "value": config.ScriptStream,
	})
	set := raw.(map[string]interface{})
	if status != 1 || set["status"] != "success" || len(set) != 3 {
		t.Fatalf("SET returned non-message payload: %v", raw)
	}
	status, raw = executeConfiguration(store, protocol.ConfigurationReset, map[string]interface{}{
		"key": config.ScriptOutputConfig,
	})
	reset := raw.(map[string]interface{})
	if status != 1 || len(reset) != 3 {
		t.Fatalf("RESET returned non-message payload: %v", raw)
	}
	status, text := runtimeSetCommand("--json", store)
	var rows []map[string]interface{}
	if status != 1 || json.Unmarshal([]byte(text), &rows) != nil || len(rows) == 0 || len(rows[0]) != 5 {
		t.Fatalf("CLI GET must have five columns: %s", text)
	}
	status, text = runtimeSetCommand("SCRIPT_DEFAULT_OUTPUT_MODE stream --json", store)
	var message map[string]interface{}
	if status != 1 || json.Unmarshal([]byte(text), &message) != nil || len(message) != 2 {
		t.Fatalf("CLI SET must return only status/message: %s", text)
	}
}
