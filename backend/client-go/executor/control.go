package executor

import "context"

type ControlHandler func(context.Context, *Session, int, string, map[string]interface{}, func(int, string)) (int, interface{})

type ControlDomain struct {
	Execute          ControlHandler
	CancelledMessage string
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
	return RunExternalPythonScript(ctx, s, source, params, emit)
}

func (s *Session) ControlHandler(domain string) (ControlDomain, bool) {
	handler, ok := s.controlHandlers[domain]
	return handler, ok
}
