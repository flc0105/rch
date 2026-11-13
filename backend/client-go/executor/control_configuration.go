package executor

import (
	"client-go/config"
	"context"
)

const configurationDomain = "configuration"
const configGet = "get"
const configSet = "set"
const configReset = "reset"

type ConfigurationManager struct{}

func (ConfigurationManager) Execute(_ context.Context, _ *Session, _ int, action string, payload map[string]interface{}, _ func(int, string)) (int, interface{}) {
	return executeConfiguration(config.Runtime(), action, payload)
}

func executeConfiguration(store *config.RuntimeStore, action string, payload map[string]interface{}) (int, interface{}) {
	if err := store.LoadError(); err != nil {
		return 0, err.Error()
	}
	key, _ := payload["key"].(string)
	switch action {
	case configGet:
	case configSet:
		value, ok := payload["value"]
		if !ok {
			return 0, "Config value is required"
		}
		if _, err := store.SetValue(key, value); err != nil {
			return 0, err.Error()
		}
	case configReset:
		if err := store.Reset(key); err != nil {
			return 0, err.Error()
		}
	default:
		return 0, "Unsupported configuration Control action"
	}
	return 1, store.Payload()
}
