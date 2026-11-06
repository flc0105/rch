package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestRuntimeDefaultsAndPersistence(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "runtime_config_go.json")
	store := NewRuntimeStore(path)
	if store.LoadError() != nil {
		t.Fatal(store.LoadError())
	}
	if store.Seconds("COMMAND_DEFAULT_SHELL_TIMEOUT") != 30 || store.Seconds("COMMAND_DEFAULT_STREAM_TIMEOUT") != 300 || store.Seconds("SCRIPT_DEFAULT_TIMEOUT") != 300 || store.PythonPath() != "" {
		t.Fatal("incorrect defaults")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("default-only config should not be written")
	}
	if src, err := store.Set("SCRIPT_PYTHON_PATH", `C:\Program Files\Python312\python.exe`); err != nil || src != "override" {
		t.Fatalf("set: %s %v", src, err)
	}
	if src, err := store.Set("COMMAND_DEFAULT_STREAM_TIMEOUT", "18"); err != nil || src != "override" {
		t.Fatalf("timeout set: %s %v", src, err)
	}
	reloaded := NewRuntimeStore(path)
	if reloaded.PythonPath() != `C:\Program Files\Python312\python.exe` || reloaded.Seconds("COMMAND_DEFAULT_STREAM_TIMEOUT") != 18 {
		t.Fatalf("persistence failed: %#v", reloaded.overrides)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var disk map[string]interface{}
	if err := json.Unmarshal(data, &disk); err != nil {
		t.Fatal(err)
	}
	if len(disk) != 2 {
		t.Fatalf("unexpected persisted values: %v", disk)
	}
	if err := reloaded.Reset("SCRIPT_PYTHON_PATH"); err != nil {
		t.Fatal(err)
	}
	if _, err := reloaded.Set("COMMAND_DEFAULT_STREAM_TIMEOUT", "300"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("reset should delete override file: %v", err)
	}
}

func TestRuntimeConfigJsonContract(t *testing.T) {
	store := NewRuntimeStore(filepath.Join(t.TempDir(), "settings.json"))
	payload := store.Payload()
	if payload["store_path"] != store.path {
		t.Fatal("incorrect store path")
	}
	items, ok := payload["items"].([]map[string]interface{})
	if !ok || len(items) != 4 {
		t.Fatalf("expected exactly four exposed items: %#v", payload)
	}
	keys := make([]string, 0, len(items))
	for _, item := range items {
		keys = append(keys, item["key"].(string))
		for _, field := range []string{"value", "default_value", "source", "group", "desc", "value_type", "choices", "min_value", "max_value", "step", "editable"} {
			if _, exists := item[field]; !exists {
				t.Fatalf("missing UI field %s", field)
			}
		}
		if item["editable"] != true {
			t.Fatal("not editable")
		}
	}
	if !reflect.DeepEqual(keys, []string{"COMMAND_DEFAULT_SHELL_TIMEOUT", "COMMAND_DEFAULT_STREAM_TIMEOUT", "SCRIPT_DEFAULT_TIMEOUT", "SCRIPT_PYTHON_PATH"}) {
		t.Fatalf("keys: %v", keys)
	}
}

func TestRuntimeInvalidInputPreservesStorage(t *testing.T) {
	path := filepath.Join(t.TempDir(), "settings.json")
	store := NewRuntimeStore(path)
	if _, err := store.Set("COMMAND_DEFAULT_SHELL_TIMEOUT", "25"); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, invalid := range []string{"0", "-1", "abc", "1.5", "86401", "25extra"} {
		if _, err := store.Set("COMMAND_DEFAULT_SHELL_TIMEOUT", invalid); err == nil {
			t.Fatalf("accepted invalid %q", invalid)
		}
	}
	if _, err := store.Set("BAD_KEY", "1"); err == nil {
		t.Fatal("accepted unknown key")
	}
	after, _ := os.ReadFile(path)
	if string(after) != string(before) || store.Seconds("COMMAND_DEFAULT_SHELL_TIMEOUT") != 25 {
		t.Fatal("invalid config changed disk or memory")
	}
	if err := os.WriteFile(path, []byte("{broken"), 0600); err != nil {
		t.Fatal(err)
	}
	corrupted := NewRuntimeStore(path)
	if corrupted.LoadError() == nil {
		t.Fatal("did not report corrupt store")
	}
	if _, err := corrupted.Set("COMMAND_DEFAULT_STREAM_TIMEOUT", "10"); err == nil {
		t.Fatal("rewrote corrupt store")
	}
}
