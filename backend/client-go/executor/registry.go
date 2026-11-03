package executor

import (
	"context"
	"fmt"
	"reflect"
	"sort"
	"strings"
	"sync"
)

type CommandHandler func(*Session, []string) (int, string)

// CommandRunner handles cancellable commands and optional interim output.
type CommandRunner func(context.Context, *Session, string, func(int, string)) (int, string)

type CommandSpec struct {
	Name         string
	Usage        string
	Help         string
	Group        string
	Suggest      bool
	CancelPolicy string
	Output       string
	Handler      CommandHandler
	Runner       CommandRunner
}

type CommandOption func(*CommandSpec)

var (
	commandRegistryMu sync.RWMutex
	commandRegistry   = map[string]CommandSpec{}

	sessionPtrType    = reflect.TypeOf((*Session)(nil))
	stringSliceType   = reflect.TypeOf([]string(nil))
	commandHandlerTyp = reflect.TypeOf((CommandHandler)(nil))
)

func Register(name string, parts ...interface{}) struct{} {
	spec := CommandSpec{
		Name:         strings.TrimSpace(strings.ToLower(name)),
		Group:        "misc",
		CancelPolicy: "none",
		Output:       "collect",
	}

	if spec.Name == "" {
		panic("command name is required")
	}

	for _, part := range parts {
		switch v := part.(type) {
		case CommandOption:
			v(&spec)

		case CommandRunner:
			if spec.Handler != nil || spec.Runner != nil {
				panic(fmt.Sprintf("duplicate handler for command: %s", spec.Name))
			}
			spec.Runner = v

		case CommandHandler:
			if spec.Handler != nil || spec.Runner != nil {
				panic(fmt.Sprintf("duplicate handler for command: %s", spec.Name))
			}
			spec.Handler = v

		default:
			handler, ok := tryConvertHandler(part)
			if ok {
				if spec.Handler != nil || spec.Runner != nil {
					panic(fmt.Sprintf("duplicate handler for command: %s", spec.Name))
				}
				spec.Handler = handler
				continue
			}

			panic(fmt.Sprintf("unsupported register part for command %s: %T", spec.Name, part))
		}
	}

	if spec.Handler == nil && spec.Runner == nil {
		panic(fmt.Sprintf("command handler is required: %s", spec.Name))
	}

	spec.Group = normalizeGroup(spec.Group)

	commandRegistryMu.Lock()
	defer commandRegistryMu.Unlock()

	if _, exists := commandRegistry[spec.Name]; exists {
		panic(fmt.Sprintf("duplicate command registration: %s", spec.Name))
	}
	commandRegistry[spec.Name] = spec

	return struct{}{}
}

func tryConvertHandler(part interface{}) (CommandHandler, bool) {
	if part == nil {
		return nil, false
	}

	value := reflect.ValueOf(part)
	typ := value.Type()

	if typ.Kind() != reflect.Func {
		return nil, false
	}

	if !isValidHandlerFuncType(typ) {
		return nil, false
	}

	converted := value.Convert(commandHandlerTyp)
	handler, ok := converted.Interface().(CommandHandler)
	return handler, ok
}

func isValidHandlerFuncType(t reflect.Type) bool {
	if t.NumIn() != 2 || t.NumOut() != 2 {
		return false
	}

	if t.In(0) != sessionPtrType {
		return false
	}

	if t.In(1) != stringSliceType {
		return false
	}

	if t.Out(0).Kind() != reflect.Int {
		return false
	}

	if t.Out(1).Kind() != reflect.String {
		return false
	}

	return true
}

func Usage(value string) CommandOption {
	return func(spec *CommandSpec) {
		spec.Usage = strings.TrimSpace(value)
	}
}

func Help(value string) CommandOption {
	return func(spec *CommandSpec) {
		spec.Help = strings.TrimSpace(value)
	}
}

func Group(value string) CommandOption {
	return func(spec *CommandSpec) {
		spec.Group = strings.TrimSpace(strings.ToLower(value))
	}
}

func Output(value string) CommandOption {
	return func(spec *CommandSpec) {
		spec.Output = value
	}
}

func CancelPolicy(value string) CommandOption {
	return func(spec *CommandSpec) {
		spec.CancelPolicy = value
	}
}

func Suggest() CommandOption {
	return func(spec *CommandSpec) {
		spec.Suggest = true
	}
}

func LookupCommand(name string) (CommandSpec, bool) {
	commandRegistryMu.RLock()
	defer commandRegistryMu.RUnlock()

	spec, ok := commandRegistry[strings.ToLower(strings.TrimSpace(name))]
	return spec, ok
}

func AllCommands() []CommandSpec {
	commandRegistryMu.RLock()
	defer commandRegistryMu.RUnlock()

	items := make([]CommandSpec, 0, len(commandRegistry))
	for _, spec := range commandRegistry {
		items = append(items, spec)
	}

	sort.Slice(items, func(i, j int) bool {
		if items[i].Group != items[j].Group {
			return items[i].Group < items[j].Group
		}
		return items[i].Name < items[j].Name
	})

	return items
}

func CommandManifest() []interface{} {
	commands := AllCommands()
	result := make([]interface{}, 0, len(commands))
	for _, cmd := range commands {
		result = append(result, map[string]interface{}{
			"name":          cmd.Name,
			"usage":         defaultUsage(cmd),
			"help":          cmd.Help,
			"group":         cmd.Group,
			"suggest":       cmd.Suggest,
			"cancel_policy": cmd.CancelPolicy,
			"output":        cmd.Output,
		})
	}
	return result
}

func RenderHelpText() string {
	commands := AllCommands()
	if len(commands) == 0 {
		return "No builtin commands registered."
	}

	groups := map[string][]CommandSpec{}
	groupNames := make([]string, 0)

	for _, cmd := range commands {
		group := cmd.Group
		if _, ok := groups[group]; !ok {
			groupNames = append(groupNames, group)
		}
		groups[group] = append(groups[group], cmd)
	}

	sort.Strings(groupNames)

	lines := make([]string, 0, len(commands)+8)
	for idx, group := range groupNames {
		if idx > 0 {
			lines = append(lines, "")
		}

		lines = append(lines, "["+displayGroup(group)+"]")
		cmds := groups[group]
		sort.Slice(cmds, func(i, j int) bool { return cmds[i].Name < cmds[j].Name })

		maxUsageLen := 0
		for _, cmd := range cmds {
			u := defaultUsage(cmd)
			if len(u) > maxUsageLen {
				maxUsageLen = len(u)
			}
		}

		for _, cmd := range cmds {
			lines = append(lines, fmt.Sprintf("%-*s  %s", maxUsageLen, defaultUsage(cmd), cmd.Help))
		}
	}

	lines = append(lines, "", "[Shell]", "<other command>  Run in system shell when no builtin command matches")
	return strings.Join(lines, "\n")
}

func normalizeGroup(group string) string {
	group = strings.TrimSpace(strings.ToLower(group))
	if group == "" {
		return "misc"
	}
	return group
}

func displayGroup(group string) string {
	switch group {
	case "session":
		return "Session"
	case "platform":
		return "Platform"
	case "file":
		return "File"
	default:
		if group == "" {
			return "Misc"
		}
		return strings.ToUpper(group[:1]) + group[1:]
	}
}

func defaultUsage(spec CommandSpec) string {
	if strings.TrimSpace(spec.Usage) != "" {
		return strings.TrimSpace(spec.Usage)
	}
	return spec.Name
}
