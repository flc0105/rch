package executor

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Path completion is used by Web Terminal and RCHCLI, including the local
// `edit` command; it does not execute the requested command.
var _ = Register(
	"command_completions",
	Usage("command_completions <payload>"),
	Help("Resolve command autocomplete candidates"),
	Group("session"),
	CommandRunner(completeFileSystemCommands),
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

func completeFileSystemCommands(ctx context.Context, session *Session, raw string, _ func(int, string)) (int, string) {
	payload, err := payloadMap(raw)
	if err != nil {
		return 0, fmt.Sprintf("Invalid completion request: %v", err)
	}
	input, _ := payload["raw_input"].(string)
	cursor := len(input)
	if value, ok := payload["cursor_position"].(float64); ok && value >= 0 {
		cursor = completionCursorByteOffset(input, int(value))
	}
	prefix := strings.TrimSpace(input[:cursor])
	command, argument, hasArgument := strings.Cut(prefix, " ")
	command = strings.ToLower(command)
	if command != "cd" && command != "download" && command != "edit" {
		return jsonResult(map[string]interface{}{"items": []interface{}{}})
	}
	if !hasArgument {
		argument = ""
	}
	lookup, candidatePrefix := completionPathParts(argument)
	directory, err := remoteExisting(session, lookup, true)
	if err != nil {
		// Match Python's provider registry: invalid/unreadable directories have no candidates.
		return jsonResult(map[string]interface{}{"items": []interface{}{}})
	}
	entries, err := os.ReadDir(directory)
	if err != nil {
		return jsonResult(map[string]interface{}{"items": []interface{}{}})
	}
	items := make([]map[string]interface{}, 0, len(entries))
	for _, entry := range entries {
		if ctx.Err() != nil {
			return 0, "Command cancelled"
		}
		info, err := os.Stat(filepath.Join(directory, entry.Name()))
		if err != nil {
			continue
		}
		isDir := info.IsDir()
		if command == "cd" && !isDir {
			continue
		}
		candidatePath := candidatePrefix + entry.Name()
		kind, priority := "file", 20
		if isDir {
			kind, priority = "directory", 10
		}
		insertText := command + " " + candidatePath
		items = append(items, map[string]interface{}{
			"name": insertText, "value": insertText, "title": insertText,
			"help":   filepath.Join(directory, entry.Name()),
			"source": "client_" + command, "group": "filesystem", "kind": kind,
			"priority": priority, "candidatePath": candidatePath, "lookupPath": lookup,
			"path": filepath.Join(directory, entry.Name()), "isDir": isDir,
		})
	}
	sort.Slice(items, func(i, j int) bool {
		left, right := items[i], items[j]
		if left["priority"].(int) != right["priority"].(int) {
			return left["priority"].(int) < right["priority"].(int)
		}
		return strings.ToLower(left["candidatePath"].(string)) < strings.ToLower(right["candidatePath"].(string))
	})
	return jsonResult(map[string]interface{}{"items": items})
}
