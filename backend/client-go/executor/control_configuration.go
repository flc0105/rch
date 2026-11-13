package executor

import (
	"client-go/config"
	"client-go/protocol"
	"context"
	"strings"
)

type ConfigurationManager struct{}

func (ConfigurationManager) Execute(_ context.Context, _ *Session, _ int, action protocol.ControlAction, payload map[string]interface{}, _ func(int, string)) (int, interface{}) {
	return executeConfiguration(config.Runtime(), action, payload)
}

func executeConfiguration(store *config.RuntimeStore, action protocol.ControlAction, payload map[string]interface{}) (int, interface{}) {
	if err := store.LoadError(); err != nil {
		return 0, err.Error()
	}
	key, _ := payload["key"].(string)
	var change map[string]interface{}
	switch action {
	case protocol.ConfigurationGet:
	case protocol.ConfigurationSet:
		value, ok := payload["value"]
		if !ok {
			return 0, "Config value is required"
		}
		key = strings.ToUpper(strings.TrimSpace(key))
		old := store.Get(key)
		var err error
		switch payload["value_format"] {
		case "text":
			raw, ok := value.(string)
			if !ok {
				return 0, "Invalid configuration value format"
			}
			_, err = store.Set(key, raw)
		case nil, "typed":
			_, err = store.SetValue(key, value)
		default:
			return 0, "Invalid configuration value format"
		}
		if err != nil {
			return 0, err.Error()
		}
		change = map[string]interface{}{"key": key, "old_value": old, "new_value": store.Get(key)}
	case protocol.ConfigurationReset:
		if payload["all"] == true {
			if key != "" {
				return 0, "Specify a key or reset all"
			}
			if err := store.ResetAll(); err != nil {
				return 0, err.Error()
			}
		} else {
			key = strings.ToUpper(strings.TrimSpace(key))
			old := store.Get(key)
			if err := store.Reset(key); err != nil {
				return 0, err.Error()
			}
			change = map[string]interface{}{"key": key, "old_value": old, "new_value": store.Get(key)}
		}
	default:
		return 0, "Unsupported configuration Control action"
	}
	result := store.Payload()
	if change != nil {
		result["change"] = change
	}
	return 1, result
}
