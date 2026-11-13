package executor

import (
	"client-go/config"
	"context"
)

type ControlHandler func(context.Context, *Session, int, string, map[string]interface{}, func(int, string)) (int, interface{})

type ControlDomain struct {
	Execute          ControlHandler
	CancelledMessage string
	NonCancellable   bool
}

type ScriptManager struct{}

func (ScriptManager) Execute(ctx context.Context, s *Session, id int, action string, payload map[string]interface{}, emit func(int, string)) (int, interface{}) {
	if action != "run" {
		return 0, "Unsupported script Control action: " + action
	}
	source, ok := payload["source"].(string)
	if !ok || source == "" {
		return 0, "Invalid script Control source"
	}
	args, ok := payload["params"].(map[string]interface{})
	if !ok {
		return 0, "Invalid script Control parameters"
	}
	name, ok := payload["script_name"].(string)
	if !ok || name == "" {
		return 0, "Invalid script Control name"
	}
	params := make(map[string]interface{}, len(args)+1)
	for key, value := range args {
		params[key] = value
	}
	params["__script_name__"] = name
	executionMode, _ := payload["execution_mode"].(string)
	outputMode, _ := payload["output_mode"].(string)
	if executionMode != config.ScriptSubprocessPipe {
		return 0, "Invalid or unavailable Script execution_mode"
	}
	result := runExternalPythonScriptMode(ctx, s, source, params, emit, config.Runtime(), outputMode)
	if result.Reason != "" {
		kind := "error"
		if result.Reason == "cancelled" {
			kind = "cancelled"
		}
		return result.Status, map[string]interface{}{"event_type": kind, "failure_reason": result.Reason, "text": result.Text}
	}
	return result.Status, result.Text
}

func (s *Session) ControlHandler(domain string) (ControlDomain, bool) {
	handler, ok := s.controlHandlers[domain]
	return handler, ok
}
