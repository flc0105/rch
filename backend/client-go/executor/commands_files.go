package executor

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// These commands use the same structured-argument and result contracts as the
// Python Client, so the existing Remote Files Server API needs no Go-specific path.
var (
	_ = Register("browse_dir", Usage("browse_dir <path>"), Help("Browse a remote directory"), Group("file_path"), CancelPolicy("cooperative"), CommandRunner(browseDir))
	_ = Register("mkdir_path", Usage("mkdir_path <path>"), Help("Create a directory"), Group("file_path"), CommandRunner(simpleRemoteRunner(mkdirPath)))
	_ = Register("rename_path", Usage("rename_path <payload>"), Help("Rename a file or directory"), Group("file_path"), CommandRunner(simpleRemoteRunner(renamePath)))
	_ = Register("delete_path", Usage("delete_path <path>"), Help("Delete a file or directory"), Group("file_path"), CancelPolicy("cooperative"), CommandRunner(deletePath))
	_ = Register("delete_paths", Usage("delete_paths <payload>"), Help("Delete multiple paths"), Group("file_path"), CancelPolicy("cooperative"), CommandRunner(deletePaths))
	_ = Register("paste_paths", Usage("paste_paths <payload>"), Help("Copy or move paths"), Group("file_path"), CancelPolicy("cooperative"), CommandRunner(pastePaths))
)

// Run fast filesystem mutations without blocking the socket's heartbeat loop.
func simpleRemoteRunner(handler CommandHandler) CommandRunner {
	return func(ctx context.Context, session *Session, raw string, _ func(int, string)) (int, string) {
		if ctx.Err() != nil {
			return 0, "Command cancelled"
		}
		return handler(session, strings.Fields(raw))
	}
}

func remotePayload(raw string) (interface{}, error) {
	raw = strings.TrimSpace(raw)
	if !strings.HasPrefix(raw, "__json__:") {
		return raw, nil
	}
	encoded := strings.TrimPrefix(raw, "__json__:")
	data, err := base64.URLEncoding.DecodeString(encoded)
	if err != nil {
		return nil, fmt.Errorf("invalid structured argument: %w", err)
	}
	var payload interface{}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, fmt.Errorf("invalid structured JSON: %w", err)
	}
	return payload, nil
}

func payloadMap(raw string) (map[string]interface{}, error) {
	value, err := remotePayload(raw)
	if err != nil {
		return nil, err
	}
	payload, ok := value.(map[string]interface{})
	if !ok {
		return nil, fmt.Errorf("expected structured JSON object")
	}
	return payload, nil
}

func payloadText(v interface{}) string {
	text, _ := v.(string)
	return strings.TrimSpace(text)
}

func payloadBool(value interface{}) bool {
	switch v := value.(type) {
	case bool:
		return v
	case string:
		switch strings.ToLower(strings.TrimSpace(v)) {
		case "true", "yes", "on", "1":
			return true
		}
	case float64:
		return v != 0
	}
	return false
}

func payloadPositiveInt(value interface{}, fallback, maximum int) int {
	var n int
	switch v := value.(type) {
	case float64:
		if v > 0 && v < float64(int(^uint(0)>>1)) {
			n = int(v)
		}
	case string:
		n, _ = strconv.Atoi(strings.TrimSpace(v))
	}
	if n <= 0 {
		n = fallback
	}
	if maximum > 0 && n > maximum {
		n = maximum
	}
	return n
}

func remotePath(s *Session, raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		raw = s.Cwd
	}
	if raw == "~" || strings.HasPrefix(raw, "~/") || strings.HasPrefix(raw, `~\`) {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		raw = filepath.Join(home, strings.TrimLeft(raw[1:], `/\`))
	}
	if !filepath.IsAbs(raw) {
		raw = filepath.Join(s.Cwd, raw)
	}
	return filepath.Abs(raw)
}

func remoteExisting(s *Session, raw string, wantDirectory bool) (string, error) {
	path, err := remotePath(s, raw)
	if err != nil {
		return "", err
	}
	info, err := os.Stat(path)
	if err != nil {
		return "", err
	}
	if wantDirectory && !info.IsDir() {
		return "", fmt.Errorf("not a directory: %s", path)
	}
	return path, nil
}

func jsonResult(value interface{}) (int, string) {
	data, err := json.Marshal(value)
	if err != nil {
		return 0, fmt.Sprintf("Failed to encode result: %v", err)
	}
	return 1, string(data)
}

func pathArgument(raw string) (string, error) {
	value, err := remotePayload(raw)
	if err != nil {
		return "", err
	}
	if payload, ok := value.(map[string]interface{}); ok {
		return payloadText(payload["path"]), nil
	}
	return payloadText(value), nil
}

func browseDir(ctx context.Context, s *Session, raw string, _ func(int, string)) (int, string) {
	value, err := remotePayload(raw)
	if err != nil {
		return 0, fmt.Sprintf("Failed to browse directory: %v", err)
	}
	payload, _ := value.(map[string]interface{})
	path := payloadText(value)
	page, pageSize := 1, 100
	showHidden, recursive := false, false
	keyword := ""
	if payload != nil {
		path = payloadText(payload["path"])
		page = payloadPositiveInt(payload["page"], 1, 0)
		pageSize = payloadPositiveInt(payload["page_size"], 100, 500)
		showHidden = payloadBool(payload["show_hidden"])
		recursive = payloadBool(payload["recursive_search"])
		keyword = payloadText(payload["search_keyword"])
		if keyword == "" {
			keyword = payloadText(payload["search"])
		}
	}
	directory, err := remoteExisting(s, path, true)
	if err != nil {
		return 0, fmt.Sprintf("Failed to browse directory: %v", err)
	}
	result, err := listRemoteDirectory(ctx, directory, page, pageSize, showHidden, keyword, recursive)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return 0, "Command cancelled"
		}
		return 0, fmt.Sprintf("Failed to browse directory: %v", err)
	}
	return jsonResult(result)
}

type remoteEntry struct {
	Name         string `json:"name"`
	Path         string `json:"path"`
	IsDir        bool   `json:"is_dir"`
	IsSymlink    bool   `json:"is_symlink"`
	IsHidden     bool   `json:"is_hidden"`
	Size         int64  `json:"size"`
	ModifiedAt   string `json:"modified_at"`
	ParentPath   string `json:"parent_path"`
	RelativePath string `json:"relative_path"`
}

func listRemoteDirectory(ctx context.Context, directory string, page, pageSize int, showHidden bool, keyword string, recursive bool) (map[string]interface{}, error) {
	recursive = recursive && keyword != ""
	keywordLower := strings.ToLower(keyword)
	all := make([]remoteEntry, 0)
	var scan func(string) error
	scan = func(dir string) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		children, err := os.ReadDir(dir)
		if err != nil {
			return err
		}
		for _, child := range children {
			if err := ctx.Err(); err != nil {
				return err
			}
			path := filepath.Join(dir, child.Name())
			info, err := os.Lstat(path)
			if err != nil {
				continue // An entry may disappear while its directory is scanned.
			}
			isSymlink := info.Mode()&os.ModeSymlink != 0
			isDir := info.IsDir()
			if isSymlink {
				if target, err := os.Stat(path); err == nil {
					isDir = target.IsDir()
				}
			}
			hidden := isHiddenRemoteFile(child.Name(), info)
			relative, _ := filepath.Rel(directory, path)
			entry := remoteEntry{
				Name: child.Name(), Path: path, IsDir: isDir, IsSymlink: isSymlink,
				IsHidden: hidden, Size: info.Size(), ModifiedAt: info.ModTime().Local().Format("2006-01-02 15:04:05"),
				ParentPath: dir, RelativePath: relative,
			}
			if isDir {
				entry.Size = 0
			}
			if keywordLower == "" || strings.Contains(strings.ToLower(entry.Name), keywordLower) {
				all = append(all, entry)
			}
			if recursive && isDir && !isSymlink && (showHidden || !hidden) {
				// Match Python Client: an unreadable descendant does not fail the whole listing.
				if err := scan(path); err != nil && errors.Is(err, context.Canceled) {
					return err
				}
			}
		}
		return nil
	}
	if err := scan(directory); err != nil {
		return nil, err
	}
	sort.Slice(all, func(i, j int) bool {
		if all[i].IsDir != all[j].IsDir {
			return all[i].IsDir
		}
		left, right := all[i].Name, all[j].Name
		if recursive {
			left, right = all[i].RelativePath, all[j].RelativePath
		}
		return strings.ToLower(left) < strings.ToLower(right)
	})
	totalHidden := 0
	visible := make([]remoteEntry, 0, len(all))
	for _, entry := range all {
		if entry.IsHidden {
			totalHidden++
		}
		if showHidden || !entry.IsHidden {
			visible = append(visible, entry)
		}
	}
	totalPages := (len(visible) + pageSize - 1) / pageSize
	if totalPages < 1 {
		totalPages = 1
	}
	if page > totalPages {
		page = totalPages
	}
	start := (page - 1) * pageSize
	end := start + pageSize
	if end > len(visible) {
		end = len(visible)
	}
	entries := visible[start:end]
	parent := interface{}(nil)
	if filepath.Dir(directory) != directory {
		parent = filepath.Dir(directory)
	}
	return map[string]interface{}{
		"current_path": directory, "parent_path": parent, "entries": entries,
		"pagination": map[string]interface{}{
			"page": page, "page_size": pageSize, "total_visible": len(visible), "total_pages": totalPages, "returned": len(entries),
		},
		"summary": map[string]interface{}{
			"total_all": len(all), "total_hidden": totalHidden, "show_hidden": showHidden,
			"search_keyword": keyword, "recursive_search": recursive,
		},
	}, nil
}

func mkdirPath(s *Session, args []string) (int, string) {
	raw, err := pathArgument(strings.Join(args, " "))
	if err != nil || raw == "" {
		return 0, "Failed to create directory: path is required"
	}
	path, err := remotePath(s, raw)
	if err == nil {
		_, err = os.Lstat(path)
		if err == nil {
			return 0, fmt.Sprintf("Failed to create directory: path already exists: %s", path)
		}
		if !errors.Is(err, os.ErrNotExist) {
			return 0, fmt.Sprintf("Failed to create directory: %v", err)
		}
		err = os.MkdirAll(path, 0755)
	}
	if err != nil {
		return 0, fmt.Sprintf("Failed to create directory: %v", err)
	}
	return 1, "Directory created: " + path
}

func renamePath(s *Session, args []string) (int, string) {
	payload, err := payloadMap(strings.Join(args, " "))
	if err != nil {
		return 0, "Failed to rename path: " + err.Error()
	}
	oldPath := payloadText(payload["old_path"])
	if oldPath == "" {
		return 0, "Failed to rename path: old_path is required"
	}
	oldPath, err = remotePath(s, oldPath)
	if err != nil {
		return 0, "Failed to rename path: " + err.Error()
	}
	if _, err := os.Lstat(oldPath); err != nil {
		return 0, "Failed to rename path: " + err.Error()
	}
	newPath := payloadText(payload["new_path"])
	if newPath == "" {
		newName := payloadText(payload["new_name"])
		if newName == "" || newName == "." || newName == ".." || filepath.Base(newName) != newName || strings.ContainsAny(newName, `/\`) {
			return 0, "Failed to rename path: invalid new name"
		}
		newPath = filepath.Join(filepath.Dir(oldPath), newName)
	} else {
		newPath, err = remotePath(s, newPath)
		if err != nil {
			return 0, "Failed to rename path: " + err.Error()
		}
	}
	if _, err := os.Lstat(newPath); err == nil {
		return 0, "Failed to rename path: destination already exists"
	} else if !errors.Is(err, os.ErrNotExist) {
		return 0, "Failed to rename path: " + err.Error()
	}
	if err := os.Rename(oldPath, newPath); err != nil {
		return 0, "Failed to rename path: " + err.Error()
	}
	return 1, "Renamed to: " + newPath
}

func deleteRemotePath(ctx context.Context, path string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if filepath.Dir(path) == path { // Never delete a filesystem volume root.
		return fmt.Errorf("cannot delete filesystem root")
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if info.IsDir() {
		children, err := os.ReadDir(path)
		if err != nil {
			return err
		}
		for _, child := range children {
			if err := deleteRemotePath(ctx, filepath.Join(path, child.Name())); err != nil && !errors.Is(err, os.ErrNotExist) {
				return err
			}
		}
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	return os.Remove(path)
}

func deletePath(ctx context.Context, s *Session, raw string, _ func(int, string)) (int, string) {
	raw, err := pathArgument(raw)
	if err != nil || raw == "" {
		return 0, "Failed to delete path: path is required"
	}
	path, err := remotePath(s, raw)
	if err != nil {
		return 0, "Failed to delete path: " + err.Error()
	}
	info, err := os.Lstat(path)
	if err != nil {
		return 0, "Failed to delete path: " + err.Error()
	}
	if err := deleteRemotePath(ctx, path); err != nil {
		return 0, "Failed to delete path: " + err.Error()
	}
	if info.IsDir() {
		return 1, "Directory deleted: " + path
	}
	return 1, "File deleted: " + path
}

type batchRemoteResult struct {
	Status    int      `json:"status"`
	Total     int      `json:"total"`
	Succeeded int      `json:"succeeded"`
	Failed    int      `json:"failed"`
	Message   string   `json:"message"`
	Errors    []string `json:"errors"`
}

func (r *batchRemoteResult) appendError(path string, err error) {
	r.Errors = append(r.Errors, fmt.Sprintf("%s: %v", path, err))
}

func (r *batchRemoteResult) finish(action, destination string) {
	r.Failed = r.Total - r.Succeeded
	if r.Succeeded > 0 {
		r.Status = 1
	}
	verb := map[string]string{"delete": "Deleted", "copy": "Copied", "move": "Moved"}[action]
	r.Message = fmt.Sprintf("%s %d of %d items", verb, r.Succeeded, r.Total)
	if destination != "" {
		r.Message += " to: " + destination
	}
	if len(r.Errors) != 0 {
		r.Message += "\nErrors:\n  " + strings.Join(r.Errors, "\n  ")
	}
}

func getBatchPaths(payload map[string]interface{}) ([]string, error) {
	raw, ok := payload["paths"].([]interface{})
	if !ok || len(raw) == 0 {
		return nil, fmt.Errorf("paths must be a non-empty array")
	}
	paths := make([]string, len(raw))
	for index, value := range raw {
		path, ok := value.(string)
		if !ok || strings.TrimSpace(path) == "" {
			return nil, fmt.Errorf("paths[%d] must be a path string", index)
		}
		paths[index] = strings.TrimSpace(path)
	}
	return paths, nil
}

func deletePaths(ctx context.Context, s *Session, raw string, _ func(int, string)) (int, string) {
	payload, err := payloadMap(raw)
	if err != nil {
		return 0, "Failed to delete paths: " + err.Error()
	}
	paths, err := getBatchPaths(payload)
	if err != nil {
		return 0, "Failed to delete paths: " + err.Error()
	}
	result := batchRemoteResult{Total: len(paths), Errors: []string{}}
	for _, raw := range paths {
		if ctx.Err() != nil {
			return 0, "Command cancelled"
		}
		path, err := remotePath(s, raw)
		if err == nil {
			err = deleteRemotePath(ctx, path)
		}
		if err != nil {
			result.appendError(raw, err)
		} else {
			result.Succeeded++
		}
	}
	result.finish("delete", "")
	return jsonResult(result)
}

func pastePaths(ctx context.Context, s *Session, raw string, _ func(int, string)) (int, string) {
	payload, err := payloadMap(raw)
	if err != nil {
		return 0, "Failed to paste paths: " + err.Error()
	}
	paths, err := getBatchPaths(payload)
	if err != nil {
		return 0, "Failed to paste paths: " + err.Error()
	}
	operation := payloadText(payload["operation"])
	if operation == "" {
		operation = "copy"
	}
	if operation != "copy" && operation != "move" {
		return 0, "Failed to paste paths: operation must be copy or move"
	}
	destination := payloadText(payload["destination_dir"])
	if destination == "" {
		return 0, "Failed to paste paths: destination_dir is required"
	}
	destination, err = remoteExisting(s, destination, true)
	if err != nil {
		return 0, "Failed to paste paths: " + err.Error()
	}
	result := batchRemoteResult{Total: len(paths), Errors: []string{}}
	for _, raw := range paths {
		if ctx.Err() != nil {
			return 0, "Command cancelled"
		}
		source, err := remotePath(s, raw)
		if err == nil {
			err = copyOrMovePath(ctx, source, destination, operation)
		}
		if err != nil {
			result.appendError(raw, err)
		} else {
			result.Succeeded++
		}
	}
	result.finish(operation, destination)
	return jsonResult(result)
}

func copyOrMovePath(ctx context.Context, source, directory, operation string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	info, err := os.Lstat(source)
	if err != nil {
		return err
	}
	target := filepath.Join(directory, filepath.Base(source))
	if source == target {
		return fmt.Errorf("source and target are the same")
	}
	if _, err := os.Lstat(target); err == nil {
		return fmt.Errorf("target already exists: %s", target)
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if info.IsDir() {
		rel, err := filepath.Rel(source, directory)
		if err != nil {
			return err
		}
		if rel == "." || (rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) && !filepath.IsAbs(rel)) {
			return fmt.Errorf("cannot %s a directory into itself or its subdirectory", operation)
		}
	}
	if operation == "move" {
		if err := os.Rename(source, target); err == nil {
			return nil
		} else if !errors.Is(err, syscall.EXDEV) {
			return err
		}
	}
	if err := copyRemotePath(ctx, source, target); err != nil {
		return err
	}
	if operation == "move" {
		return deleteRemotePath(ctx, source)
	}
	return nil
}

func copyRemotePath(ctx context.Context, source, target string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	info, err := os.Lstat(source)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 {
		link, err := os.Readlink(source)
		if err != nil {
			return err
		}
		return os.Symlink(link, target)
	}
	if info.IsDir() {
		if err := os.Mkdir(target, info.Mode().Perm()); err != nil {
			return err
		}
		entries, err := os.ReadDir(source)
		if err != nil {
			return err
		}
		for _, entry := range entries {
			if err := copyRemotePath(ctx, filepath.Join(source, entry.Name()), filepath.Join(target, entry.Name())); err != nil {
				return err
			}
		}
		return nil
	}
	if !info.Mode().IsRegular() {
		return fmt.Errorf("unsupported special file: %s", source)
	}
	input, err := os.Open(source)
	if err != nil {
		return err
	}
	defer input.Close()
	output, err := os.OpenFile(target, os.O_WRONLY|os.O_CREATE|os.O_EXCL, info.Mode().Perm())
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(output, contextReader{ctx: ctx, reader: input})
	closeErr := output.Close()
	if copyErr != nil {
		return copyErr
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Chtimes(target, time.Now(), info.ModTime())
}

// Long copies periodically check cancellation while keeping the socket loop free
// for heartbeat and cancellation messages.
type contextReader struct {
	ctx    context.Context
	reader io.Reader
}

func (r contextReader) Read(p []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.reader.Read(p)
}
