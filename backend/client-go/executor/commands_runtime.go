package executor

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"unicode"

	"client-go/config"
	"client-go/protocol"
)

var _ = Register("set", Usage("set [--json | --reset KEY | KEY value]"), Help("View or update runtime configuration"), Group("runtime"), CommandRunner(cmdRuntimeSet))

// splitRuntimeArgs accepts Server-generated POSIX shell quotes while keeping
// Windows backslashes literal (including paths containing spaces).
func splitRuntimeArgs(raw string) ([]string, error) {
	var words []string
	var part strings.Builder
	quote := rune(0)
	started := false
	for _, ch := range raw {
		switch {
		case quote != 0:
			if ch == quote {
				quote = 0
			} else {
				part.WriteRune(ch)
			}
		case ch == '\'' || ch == '"':
			quote = ch
			started = true
		case unicode.IsSpace(ch):
			if started {
				words = append(words, part.String())
				part.Reset()
				started = false
			}
		default:
			part.WriteRune(ch)
			started = true
		}
	}
	if quote != 0 {
		return nil, fmt.Errorf("unterminated quoted value")
	}
	if started {
		words = append(words, part.String())
	}
	return words, nil
}

func cmdRuntimeSet(_ context.Context, _ *Session, raw string, _ func(int, string)) (int, string) {
	return runtimeSetCommand(raw, config.Runtime())
}

func runtimeSetCommand(raw string, store *config.RuntimeStore) (int, string) {
	parts, err := splitRuntimeArgs(raw)
	if err != nil {
		return 0, fmt.Sprintf("Invalid set arguments: %v", err)
	}
	jsonOutput := len(parts) == 1 && parts[0] == "--json"
	if !jsonOutput && len(parts) > 1 && parts[len(parts)-1] == "--json" &&
		!(len(parts) == 2 && !strings.HasPrefix(parts[0], "--")) {
		jsonOutput = true
		parts = parts[:len(parts)-1]
	} else if jsonOutput {
		parts = nil
	}
	action := protocol.ConfigurationGet
	payload := map[string]interface{}{}
	switch {
	case len(parts) == 0:
	case len(parts) == 1 && parts[0] == "--all":
		payload["include_hidden"] = true
	case len(parts) == 1 && parts[0] == "--reset-all":
		action = protocol.ConfigurationReset
		payload["all"] = true
	case len(parts) == 2 && parts[0] == "--reset":
		action = protocol.ConfigurationReset
		payload["key"] = parts[1]
	case len(parts) == 2 && !strings.HasPrefix(parts[0], "--"):
		action = protocol.ConfigurationSet
		payload["key"] = parts[0]
		payload["value"] = parts[1]
		payload["value_format"] = "text"
	default:
		message := "Usage: set [--json | --all [--json] | --reset KEY [--json] | --reset-all [--json] | KEY value [--json]]"
		if jsonOutput {
			raw, _ := json.Marshal(map[string]interface{}{"status": "error", "message": message})
			return 0, string(raw)
		}
		return 0, message
	}
	status, result := executeConfiguration(store, action, payload)
	return renderRuntimeSetResult(status, result, jsonOutput)
}

func renderRuntimeSetResult(status int, result interface{}, jsonOutput bool) (int, string) {
	envelope, ok := result.(map[string]interface{})
	if !ok {
		return 0, "Invalid Configuration result"
	}
	if status == 1 && envelope["data"] != nil {
		configPayload, ok := envelope["data"].(map[string]interface{})
		if !ok {
			return 0, "Invalid Configuration data"
		}
		items, ok := configPayload["items"].([]map[string]interface{})
		if !ok {
			return 0, "Invalid Configuration items"
		}
		rows := make([]map[string]interface{}, 0, len(items))
		lines := []string{"key | group | value | override | default_value"}
		for _, item := range items {
			row := map[string]interface{}{
				"key": item["key"], "group": item["group"], "value": item["value"],
				"override": item["source"] == "override", "default_value": item["default_value"],
			}
			rows = append(rows, row)
			lines = append(lines, fmt.Sprintf("%v | %v | %v | %v | %v", row["key"], row["group"], row["value"], row["override"], row["default_value"]))
		}
		if jsonOutput {
			raw, err := json.Marshal(rows)
			if err != nil {
				return 0, err.Error()
			}
			return status, string(raw)
		}
		if len(rows) == 0 {
			return status, "No data to display"
		}
		return status, strings.Join(lines, "\n")
	}
	message := fmt.Sprint(envelope["message"])
	if jsonOutput {
		raw, err := json.Marshal(map[string]interface{}{"status": envelope["status"], "message": message})
		if err != nil {
			return 0, err.Error()
		}
		return status, string(raw)
	}
	return status, message
}
