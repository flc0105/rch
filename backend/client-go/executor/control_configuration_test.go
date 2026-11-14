package executor

import (
	"client-go/config"
	"client-go/protocol"
	"path/filepath"
	"testing"
)

func TestConfigurationControlSharesRuntimeStore(t *testing.T) {
	store := config.NewRuntimeStore(filepath.Join(t.TempDir(), "settings.json"))
	status, result := executeConfiguration(store, protocol.ConfigurationSet, map[string]interface{}{"key": config.ScriptOutputConfig, "value": config.ScriptStream})
	if status != 1 || store.Get(config.ScriptOutputConfig) != config.ScriptStream {
		t.Fatalf("set: %v %v", status, result)
	}
	status, _ = executeConfiguration(store, protocol.ConfigurationSet, map[string]interface{}{
		"key": config.ScriptOutputConfig, "value": config.ScriptCollect,
	})
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

func TestConfigurationControlResultEnvelopeAndCLIViews(t *testing.T) {
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
}
