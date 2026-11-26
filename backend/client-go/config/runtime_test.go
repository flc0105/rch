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
	if !ok || len(items) != 11 {
		t.Fatalf("expected exactly eleven exposed items: %#v", payload)
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
	if !reflect.DeepEqual(keys, []string{"COMMAND_DEFAULT_SHELL_TIMEOUT", "COMMAND_DEFAULT_STREAM_TIMEOUT", "FILE_TRANSFER_MODE", "HTTP_TRANSFER_BUFFER_SIZE", ReconnectBackoffMaxConfig, ReconnectBackoffMinConfig, "SCRIPT_DEFAULT_EXECUTION_MODE", "SCRIPT_DEFAULT_OUTPUT_MODE", "SCRIPT_DEFAULT_TIMEOUT", "SCRIPT_PYTHON_PATH", ServerInboundTimeoutConfig}) {
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

func TestTransferModeStrategyConfiguration(t *testing.T) {
	store := NewRuntimeStore(filepath.Join(t.TempDir(), "runtime.json"))
	if store.FileTransferMode() != TransferHTTPStreaming || store.TransferBufferSize() != 1048576 {
		t.Fatal("bad transfer defaults")
	}
	if _, err := store.Set(TransferModeConfig, TransferTCPStreaming); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Set(TransferBufferConfig, "65536"); err != nil {
		t.Fatal(err)
	}
	again := NewRuntimeStore(store.path)
	if again.FileTransferMode() != TransferTCPStreaming || again.TransferBufferSize() != 65536 {
		t.Fatal("transfer settings did not persist")
	}
	for _, invalid := range []string{"http_simple", "tls_tcp", "other"} {
		if _, err := store.Set(TransferModeConfig, invalid); err == nil {
			t.Fatalf("accepted invalid mode %q", invalid)
		}
	}
	if _, err := store.Set(TransferBufferConfig, "32768"); err == nil {
		t.Fatal("accepted undersized buffer")
	}
	if err := again.Reset(TransferModeConfig); err != nil {
		t.Fatal(err)
	}
	if again.FileTransferMode() != TransferHTTPStreaming {
		t.Fatal("reset did not restore default")
	}
}

func TestServerInboundTimeoutConfiguration(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.json")
	store := NewRuntimeStore(path)
	if got := store.Seconds(ServerInboundTimeoutConfig); got != 120 {
		t.Fatalf("default: %d", got)
	}
	for _, value := range []string{"-1", "1.5", "invalid"} {
		if _, err := store.Set(ServerInboundTimeoutConfig, value); err == nil {
			t.Fatalf("accepted %s", value)
		}
	}
	for _, value := range []string{"90", "0"} {
		if _, err := store.Set(ServerInboundTimeoutConfig, value); err != nil {
			t.Fatal(err)
		}
	}
	store = NewRuntimeStore(path)
	if store.LoadError() != nil || store.Seconds(ServerInboundTimeoutConfig) != 0 {
		t.Fatal("disabled timeout did not persist")
	}
	found := false
	for _, item := range store.Payload()["items"].([]map[string]interface{}) {
		if item["key"] == ServerInboundTimeoutConfig {
			found = true
			if item["min_value"] != 0 || item["max_value"] != nil || item["group"] != "connection" {
				t.Fatalf("invalid metadata: %v", item)
			}
		}
	}
	if !found {
		t.Fatal("configuration not exposed")
	}
	if err := store.Reset(ServerInboundTimeoutConfig); err != nil {
		t.Fatal(err)
	}
	if store.Seconds(ServerInboundTimeoutConfig) != 120 {
		t.Fatal("reset failed")
	}
}

func TestReconnectBackoffPairValidationAndReset(t *testing.T) {
	path := filepath.Join(t.TempDir(), "settings.json")
	store := NewRuntimeStore(path)
	for _, key := range []string{ReconnectBackoffMaxConfig, ReconnectBackoffMinConfig} {
		if _, err := store.Set(key, "60"); err != nil {
			t.Fatal(err)
		}
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct{ key, value string }{
		{ReconnectBackoffMinConfig, "61"}, {ReconnectBackoffMaxConfig, "59"},
		{ReconnectBackoffMinConfig, "0"}, {ReconnectBackoffMinConfig, "1.5"},
		{ReconnectBackoffMaxConfig, "2147483648"}, {"RECONNECT_INTERVAL_SECONDS", "10"},
	} {
		if _, err := store.Set(test.key, test.value); err == nil {
			t.Fatalf("accepted %v", test)
		}
	}
	if _, err := store.SetValue(ReconnectBackoffMinConfig, true); err == nil {
		t.Fatal("accepted bool")
	}
	if err := store.Reset(ReconnectBackoffMaxConfig); err == nil {
		t.Fatal("invalid reset accepted")
	}
	after, _ := os.ReadFile(path)
	if string(before) != string(after) {
		t.Fatal("invalid update changed persisted config")
	}
	store = NewRuntimeStore(path)
	if min, max := store.ReconnectBackoffBounds(); min != 60 || max != 60 || store.LoadError() != nil {
		t.Fatalf("loaded %d/%d: %v", min, max, store.LoadError())
	}
	if err := store.Reset(ReconnectBackoffMinConfig); err != nil {
		t.Fatal(err)
	}
	if err := store.Reset(ReconnectBackoffMaxConfig); err != nil {
		t.Fatal(err)
	}
	if min, max := store.ReconnectBackoffBounds(); min != 5 || max != 30 {
		t.Fatalf("reset %d/%d", min, max)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("default overrides remain: %v", err)
	}
}

func TestReconnectBackoffRejectsInvalidStoredPair(t *testing.T) {
	path := filepath.Join(t.TempDir(), "settings.json")
	if err := os.WriteFile(path, []byte(`{"RECONNECT_BACKOFF_MIN_SECONDS":60,"RECONNECT_BACKOFF_MAX_SECONDS":30,"SERVER_INBOUND_TIMEOUT_SECONDS":180}`), 0600); err != nil {
		t.Fatal(err)
	}
	store := NewRuntimeStore(path)
	if store.LoadError() != nil || store.Seconds(ServerInboundTimeoutConfig) != 180 {
		t.Fatal("invalid backoff pair affected independent settings")
	}
	if min, max := store.ReconnectBackoffBounds(); min != 5 || max != 30 {
		t.Fatalf("unsafe defaults %d/%d", min, max)
	}
	if _, err := store.Set(ReconnectBackoffMaxConfig, "90"); err != nil {
		t.Fatal(err)
	}
	store = NewRuntimeStore(path)
	if min, max := store.ReconnectBackoffBounds(); min != 5 || max != 90 {
		t.Fatalf("invalid persisted minimum reappeared: %d/%d", min, max)
	}
}
