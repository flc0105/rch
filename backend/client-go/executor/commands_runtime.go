package executor

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"unicode"

	"client-go/config"
)

var _ = Register("set", Usage("set [--json | --reset KEY | KEY value]"), Help("View or update runtime configuration"), Group("runtime"), Suggest(), CommandRunner(cmdRuntimeSet))

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
	if err := store.LoadError(); err != nil {
		return 0, fmt.Sprintf("Runtime config error: %v", err)
	}
	if len(parts) > 0 && parts[0] == "--json" {
		if len(parts) != 1 {
			return 0, "Usage: set --json"
		}
		payload, err := json.Marshal(store.Payload())
		if err != nil {
			return 0, err.Error()
		}
		return 1, string(payload)
	}
	if len(parts) == 2 && parts[0] == "--reset" {
		if err := store.Reset(parts[1]); err != nil {
			return 0, err.Error()
		}
		return 1, fmt.Sprintf("%s reset to default", strings.ToUpper(parts[1]))
	}
	if len(parts) == 1 && parts[0] == "--reset-all" {
		if err := store.ResetAll(); err != nil {
			return 0, err.Error()
		}
		return 1, "All runtime config overrides reset"
	}
	if len(parts) >= 2 && !strings.HasPrefix(parts[0], "--") {
		if len(parts) > 2 {
			return 0, "Usage: set KEY value"
		}
		source, err := store.Set(parts[0], parts[1])
		if err != nil {
			return 0, fmt.Sprintf("Failed to set runtime config: %v", err)
		}
		return 1, fmt.Sprintf("%s updated (%s)", strings.ToUpper(parts[0]), source)
	}
	if len(parts) == 1 && parts[0] == "--all" {
		parts = nil
	}
	if len(parts) != 0 {
		return 0, "Usage: set [--json | --all | --reset KEY | --reset-all | KEY value]"
	}
	payload := store.Payload()
	items := payload["items"].([]map[string]interface{})
	lines := []string{"Runtime config store path: " + payload["store_path"].(string)}
	for _, item := range items {
		lines = append(lines, fmt.Sprintf("%s = %v  [%s]", item["key"], item["value"], item["source"]))
	}
	return 1, strings.Join(lines, "\n")
}
