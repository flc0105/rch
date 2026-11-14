package executor

import (
	"client-go/config"
	"client-go/protocol"
	"context"
	"fmt"
	"strings"
)

type ConfigurationManager struct{}

func configurationResult(status int, action protocol.ControlAction, message string, data map[string]interface{}) (int, interface{}) {
	result := map[string]interface{}{"event_type": "completed", "status": "success", "message": message}
	if status != 1 {
		result["status"] = "error"
	} else if action == protocol.ConfigurationGet {
		result["data"] = data
	}
	return status, result
}

func (ConfigurationManager) Execute(_ context.Context, _ *Session, _ int, action protocol.ControlAction, payload map[string]interface{}, _ func(int, string)) (int, interface{}) {
	return executeConfiguration(config.Runtime(), action, payload)
}

func executeConfiguration(store *config.RuntimeStore, action protocol.ControlAction, payload map[string]interface{}) (int, interface{}) {
	if err := store.LoadError(); err != nil {
		return configurationResult(0, action, err.Error(), nil)
	}
	key, _ := payload["key"].(string)
	var change map[string]interface{}
	switch action {
	case protocol.ConfigurationGet:
	case protocol.ConfigurationSet:
		value, ok := payload["value"]
		if !ok {
			return configurationResult(0, action, "Config value is required", nil)
		}
		key = strings.ToUpper(strings.TrimSpace(key))
		old := store.Get(key)
		var err error
		switch payload["value_format"] {
		case "text":
			raw, ok := value.(string)
			if !ok {
				return configurationResult(0, action, "Invalid configuration value format", nil)
			}
			_, err = store.Set(key, raw)
		case nil, "typed":
			_, err = store.SetValue(key, value)
		default:
			return configurationResult(0, action, "Invalid configuration value format", nil)
		}
		if err != nil {
			return configurationResult(0, action, err.Error(), nil)
		}
		change = map[string]interface{}{"key": key, "old_value": old, "new_value": store.Get(key)}
	case protocol.ConfigurationReset:
		if payload["all"] == true {
			if key != "" {
				return configurationResult(0, action, "Specify a key or reset all", nil)
			}
			if err := store.ResetAll(); err != nil {
				return configurationResult(0, action, err.Error(), nil)
			}
		} else {
			key = strings.ToUpper(strings.TrimSpace(key))
			old := store.Get(key)
			if err := store.Reset(key); err != nil {
				return configurationResult(0, action, err.Error(), nil)
			}
			change = map[string]interface{}{"key": key, "old_value": old, "new_value": store.Get(key)}
		}
	default:
		return configurationResult(0, action, "Unsupported configuration Control action", nil)
	}
	if action == protocol.ConfigurationGet {
		return configurationResult(1, action, "", store.Payload())
	}
	if change == nil {
		return configurationResult(1, action, "All runtime config overrides reset to defaults.", nil)
	}
	old, newValue := formatRuntimeValue(change["old_value"]), formatRuntimeValue(change["new_value"])
	if action == protocol.ConfigurationSet {
		return configurationResult(1, action, key+" updated: "+old+" → "+newValue, nil)
	}
	return configurationResult(1, action, key+" reset to default: "+newValue, nil)
}

// formatRuntimeValue formats Configuration Control notices, not a Client CLI command.
func formatRuntimeValue(value interface{}) string {
	if text, ok := value.(string); ok {
		quoted := fmt.Sprintf("%q", text)
		return "'" + strings.ReplaceAll(strings.ReplaceAll(quoted[1:len(quoted)-1], `\"`, `"`), "'", `\'`) + "'"
	}
	return fmt.Sprint(value)
}
