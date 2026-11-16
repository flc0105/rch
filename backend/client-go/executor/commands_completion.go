package executor

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
)

func completionPathParts(argument string) (string, string) {
	text := strings.TrimSpace(argument)
	separator := strings.LastIndexAny(text, `/\`)
	if separator < 0 {
		return "", ""
	}
	if separator == len(text)-1 || separator == 0 || (separator == 2 && len(text) > 1 && text[1] == ':') {
		return text[:separator+1], text[:separator+1]
	}
	return text[:separator], text[:separator+1]
}

// Cursor positions in the Web API are JavaScript UTF-16 code units; Go strings
// use UTF-8 byte offsets. Keep Unicode paths intact during proxy completion.
func completionCursorByteOffset(input string, units int) int {
	if units <= 0 {
		return 0
	}
	used := 0
	for byteIndex, char := range input {
		width := 1
		if char > 0xFFFF {
			width = 2
		}
		if used+width > units {
			return byteIndex
		}
		used += width
	}
	return len(input)
}

func CompleteCommandCompletion(session *Session, payload map[string]interface{}) (map[string]interface{}, error) {
	input, _ := payload["raw_input"].(string)
	cursor := len(input)
	if value, ok := payload["cursor_position"].(float64); ok && value >= 0 {
		cursor = completionCursorByteOffset(input, int(value))
	} else if value, ok := payload["cursor_position"].(int); ok && value >= 0 {
		cursor = completionCursorByteOffset(input, value)
	}
	if cursor > len(input) {
		cursor = len(input)
	}

	completion, _ := payload["completion"].(map[string]interface{})
	if completion == nil {
		prefix := strings.TrimLeft(input[:cursor], " \t\r\n")
		command, _, _ := strings.Cut(prefix, " ")
		spec, registered := LookupCommand(strings.ToLower(command))
		if registered && spec.Completion != nil {
			completion = map[string]interface{}{"provider": spec.Completion.Provider, "kinds": spec.Completion.Kinds}
		}
	}
	if completion == nil {
		return map[string]interface{}{"items": []interface{}{}}, nil
	}
	provider, _ := completion["provider"].(string)
	if strings.ToLower(strings.TrimSpace(provider)) != "filesystem" {
		return map[string]interface{}{"items": []interface{}{}}, nil
	}
	allowed := map[string]bool{}
	if kinds, ok := completion["kinds"].([]interface{}); ok {
		for _, value := range kinds {
			if kind, ok := value.(string); ok {
				allowed[strings.ToLower(strings.TrimSpace(kind))] = true
			}
		}
	} else if kinds, ok := completion["kinds"].([]string); ok {
		for _, kind := range kinds {
			allowed[strings.ToLower(strings.TrimSpace(kind))] = true
		}
	}

	command := ""
	if fields := strings.Fields(input[:cursor]); len(fields) > 0 {
		command = strings.ToLower(fields[0])
	}
	start, end, rawPath := completionArgumentSpan(input, cursor)
	if command == "cd" || command == "download" || command == "edit" {
		start, end, rawPath = completionCommandTailSpan(input, cursor)
	}
	pathValue := strings.TrimSpace(rawPath)
	if len(pathValue) >= 2 && ((pathValue[0] == '"' && pathValue[len(pathValue)-1] == '"') ||
		(pathValue[0] == '\'' && pathValue[len(pathValue)-1] == '\'')) {
		pathValue = pathValue[1 : len(pathValue)-1]
	} else if strings.HasPrefix(pathValue, `"`) || strings.HasPrefix(pathValue, "'") {
		pathValue = pathValue[1:]
	}
	pathValue = strings.ReplaceAll(pathValue, `\"`, `"`)
	lookup, candidatePrefix := completionPathParts(pathValue)
	directory, err := remoteExisting(session, lookup, true)
	if err != nil {
		return map[string]interface{}{"items": []interface{}{}}, nil
	}
	entries, err := os.ReadDir(directory)
	if err != nil {
		return map[string]interface{}{"items": []interface{}{}}, nil
	}
	items := make([]map[string]interface{}, 0, len(entries))
	for _, entry := range entries {
		info, err := entry.Info()
		if err != nil {
			continue
		}
		isDir := info.IsDir()
		kind, priority := "file", 20
		if isDir {
			kind, priority = "directory", 10
		}
		if len(allowed) > 0 && !allowed[kind] {
			continue
		}
		candidatePath := candidatePrefix + entry.Name()
		replacement := candidatePath
		if strings.HasPrefix(rawPath, `"`) {
			replacement = `"` + strings.ReplaceAll(strings.ReplaceAll(candidatePath, `\`, `\\`), `"`, `\"`)
		} else if strings.HasPrefix(rawPath, "'") {
			replacement = "'" + strings.ReplaceAll(candidatePath, "'", "'\\''")
		}
		insertText := input[:start] + replacement + input[end:]
		fullPath := filepath.Join(directory, entry.Name())
		items = append(items, map[string]interface{}{
			"name": insertText, "value": insertText, "title": insertText, "insert_text": insertText,
			"help": fullPath, "source": "client_filesystem", "group": "filesystem", "kind": kind,
			"priority": priority, "candidatePath": candidatePath, "lookupPath": lookup,
			"path": fullPath, "isDir": isDir,
		})
	}
	sort.Slice(items, func(i, j int) bool {
		left, right := items[i], items[j]
		if left["priority"].(int) != right["priority"].(int) {
			return left["priority"].(int) < right["priority"].(int)
		}
		return strings.ToLower(left["candidatePath"].(string)) < strings.ToLower(right["candidatePath"].(string))
	})
	if max, ok := payload["max_results"].(float64); ok && max > 0 && int(max) < len(items) {
		items = items[:int(max)]
	}
	result := make([]interface{}, len(items))
	for i := range items {
		result[i] = items[i]
	}
	return map[string]interface{}{"items": result}, nil
}

func completionCommandTailSpan(input string, cursor int) (int, int, string) {
	prefix := input[:cursor]
	commandEnd := strings.IndexFunc(prefix, func(r rune) bool { return r == ' ' || r == '\t' || r == '\n' || r == '\r' })
	if commandEnd < 0 {
		return cursor, cursor, ""
	}
	start := commandEnd + 1
	for start < cursor && (input[start] == ' ' || input[start] == '\t') {
		start++
	}
	return start, len(input), input[start:]
}

func completionArgumentSpan(input string, cursor int) (int, int, string) {
	prefix := input[:cursor]
	start := len(prefix)
	quote := byte(0)
	escaped := false
	for i := len(prefix) - 1; i >= 0; i-- {
		ch := prefix[i]
		if escaped {
			escaped = false
			continue
		}
		if ch == '\\' && quote != '\'' {
			escaped = true
			continue
		}
		if quote != 0 {
			if ch == quote {
				quote = 0
			}
			continue
		}
		if ch == '"' || ch == '\'' {
			quote = ch
			continue
		}
		if ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r' {
			start = i + 1
			break
		}
		start = i
	}
	if len(prefix) > 0 && (prefix[len(prefix)-1] == ' ' || prefix[len(prefix)-1] == '\t') {
		start = cursor
	}
	end := cursor
	quote = 0
	escaped = false
	for i := cursor; i < len(input); i++ {
		ch := input[i]
		if escaped {
			escaped = false
			end = i + 1
			continue
		}
		if ch == '\\' && quote != '\'' {
			escaped = true
			end = i + 1
			continue
		}
		if quote != 0 {
			if ch == quote {
				quote = 0
			}
			end = i + 1
			continue
		}
		if ch == '"' || ch == '\'' {
			quote = ch
			end = i + 1
			continue
		}
		if ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r' {
			break
		}
		end = i + 1
	}
	return start, end, input[start:end]
}
