package executor

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

func remoteCommand(name string, data map[string]interface{}) string {
	payload, err := json.Marshal(data)
	if err != nil {
		panic(err)
	}
	return name + " __json__:" + base64.URLEncoding.EncodeToString(payload)
}

func testFileSession(t *testing.T) *Session {
	t.Helper()
	s := NewSession(nil, "test-client")
	s.Cwd = t.TempDir()
	return s
}

func executeRemote(t *testing.T, s *Session, cmd string) (int, string) {
	t.Helper()
	return s.Dispatch(7, cmd)
}

func decodeRemoteResult(t *testing.T, raw string) map[string]interface{} {
	t.Helper()
	var result map[string]interface{}
	if err := json.Unmarshal([]byte(raw), &result); err != nil {
		t.Fatalf("invalid JSON result: %v (%s)", err, raw)
	}
	return result
}

func TestBrowseDirMatchesWebRemoteFilesContract(t *testing.T) {
	s := testFileSession(t)
	for _, name := range []string{"z.txt", "a.txt", ".hidden", "中文.txt"} {
		if err := os.WriteFile(filepath.Join(s.Cwd, name), []byte(name), 0644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Mkdir(filepath.Join(s.Cwd, "folder"), 0755); err != nil {
		t.Fatal(err)
	}
	status, output := executeRemote(t, s, remoteCommand("browse_dir", map[string]interface{}{
		"path": s.Cwd, "page": 1, "page_size": 2, "show_hidden": false,
	}))
	if status != 1 {
		t.Fatal(output)
	}
	payload := decodeRemoteResult(t, output)
	if payload["current_path"] != s.Cwd || payload["parent_path"] != filepath.Dir(s.Cwd) {
		t.Fatalf("wrong location fields: %#v", payload)
	}
	summary := payload["summary"].(map[string]interface{})
	if summary["total_all"] != float64(5) || summary["total_hidden"] != float64(1) || summary["show_hidden"] != false {
		t.Fatalf("wrong summary: %#v", summary)
	}
	pagination := payload["pagination"].(map[string]interface{})
	if pagination["total_visible"] != float64(4) || pagination["returned"] != float64(2) || pagination["total_pages"] != float64(2) {
		t.Fatalf("wrong pagination: %#v", pagination)
	}
	entries := payload["entries"].([]interface{})
	if entries[0].(map[string]interface{})["name"] != "folder" || entries[0].(map[string]interface{})["is_dir"] != true || entries[1].(map[string]interface{})["name"] != "a.txt" {
		t.Fatalf("directory-first order lost: %#v", entries)
	}
	for _, entry := range entries {
		item := entry.(map[string]interface{})
		for _, name := range []string{"name", "path", "is_dir", "is_symlink", "is_hidden", "size", "modified_at", "parent_path", "relative_path"} {
			if _, ok := item[name]; !ok {
				t.Errorf("entry missing %q: %#v", name, item)
			}
		}
	}
	_, page2 := executeRemote(t, s, remoteCommand("browse_dir", map[string]interface{}{"page": 2, "page_size": 2}))
	second := decodeRemoteResult(t, page2)["entries"].([]interface{})
	if len(second) != 2 || second[0].(map[string]interface{})["name"] != "z.txt" || second[1].(map[string]interface{})["name"] != "中文.txt" {
		t.Fatalf("second page wrong: %#v", second)
	}
	_, hidden := executeRemote(t, s, remoteCommand("browse_dir", map[string]interface{}{"show_hidden": true, "page_size": 5000}))
	all := decodeRemoteResult(t, hidden)
	if len(all["entries"].([]interface{})) != 5 || all["pagination"].(map[string]interface{})["page_size"] != float64(500) {
		t.Fatalf("hidden or max page-size behavior wrong: %#v", all)
	}
}

func TestBrowseDirSearchRecursiveIgnoresSymlinkCyclesAndHiddenSubtrees(t *testing.T) {
	s := testFileSession(t)
	if err := os.MkdirAll(filepath.Join(s.Cwd, "dir", "deep"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(s.Cwd, ".private"), 0755); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"dir/deep/needle.txt", ".private/needle-secret.txt"} {
		if err := os.WriteFile(filepath.Join(s.Cwd, filepath.FromSlash(name)), []byte("hello"), 0644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Symlink(s.Cwd, filepath.Join(s.Cwd, "dir", "loop")); err != nil && runtime.GOOS != "windows" {
		t.Fatal(err)
	}
	cmd := remoteCommand("browse_dir", map[string]interface{}{"path": s.Cwd, "search_keyword": "needle", "recursive_search": true})
	status, text := executeRemote(t, s, cmd)
	if status != 1 {
		t.Fatal(text)
	}
	payload := decodeRemoteResult(t, text)
	entries := payload["entries"].([]interface{})
	if len(entries) != 1 || entries[0].(map[string]interface{})["relative_path"] != filepath.Join("dir", "deep", "needle.txt") {
		t.Fatalf("wrong recursive match: %#v", entries)
	}
	_, text = executeRemote(t, s, remoteCommand("browse_dir", map[string]interface{}{"search_keyword": "needle", "recursive_search": true, "show_hidden": true}))
	if got := len(decodeRemoteResult(t, text)["entries"].([]interface{})); got != 2 {
		t.Fatalf("hidden recursive results: got %d", got)
	}
	_, text = executeRemote(t, s, remoteCommand("browse_dir", map[string]interface{}{"recursive_search": true}))
	if decodeRemoteResult(t, text)["summary"].(map[string]interface{})["recursive_search"] != false {
		t.Fatal("recursive traversal should require search text")
	}
}

func TestBrowseDirRejectsInvalidPathsAndHandlesCancellation(t *testing.T) {
	s := testFileSession(t)
	if status, _ := executeRemote(t, s, "browse_dir __json__:broken"); status != 0 {
		t.Fatal("malformed input accepted")
	}
	if status, _ := executeRemote(t, s, remoteCommand("browse_dir", map[string]interface{}{"path": "missing-folder"})); status != 0 {
		t.Fatal("missing directory accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	status, text := s.DispatchContext(ctx, 10, remoteCommand("browse_dir", map[string]interface{}{}))
	if status != 0 || text != "Command cancelled" {
		t.Fatalf("cancelled browse: status=%d text=%s", status, text)
	}
	if status, _ := executeRemote(t, s, remoteCommand("browse_dir", map[string]interface{}{"page": 1000000})); status != 1 {
		t.Fatal("large page should clamp to final page")
	}
}

func TestRemoteDirectoryMutationsAndNoOverwrite(t *testing.T) {
	s := testFileSession(t)
	status, _ := executeRemote(t, s, remoteCommand("mkdir_path", map[string]interface{}{"path": "dir one/nested"}))
	if status != 1 {
		t.Fatal("failed to create nested directory")
	}
	if status, _ := executeRemote(t, s, remoteCommand("mkdir_path", map[string]interface{}{"path": "dir one/nested"})); status != 0 {
		t.Fatal("existing directory accepted")
	}
	if err := os.WriteFile(filepath.Join(s.Cwd, "name one.txt"), []byte("keep"), 0644); err != nil {
		t.Fatal(err)
	}
	status, output := executeRemote(t, s, remoteCommand("rename_path", map[string]interface{}{"old_path": "name one.txt", "new_name": "new name.txt"}))
	if status != 1 || !strings.Contains(output, "new name.txt") {
		t.Fatalf("rename failed: %d %s", status, output)
	}
	if status, _ := executeRemote(t, s, remoteCommand("rename_path", map[string]interface{}{"old_path": "new name.txt", "new_name": "../other.txt"})); status != 0 {
		t.Fatal("path traversing rename accepted")
	}
	if status, _ := executeRemote(t, s, remoteCommand("rename_path", map[string]interface{}{"old_path": "new name.txt", "new_name": "dir one"})); status != 0 {
		t.Fatal("overwrite rename accepted")
	}
	status, _ = executeRemote(t, s, remoteCommand("delete_path", map[string]interface{}{"path": "new name.txt"}))
	if status != 1 {
		t.Fatal("delete failed")
	}
	if _, err := os.Stat(filepath.Join(s.Cwd, "new name.txt")); !os.IsNotExist(err) {
		t.Fatal("deleted file still exists")
	}
	if status, _ := executeRemote(t, s, remoteCommand("delete_path", map[string]interface{}{"path": string(filepath.Separator)})); status != 0 {
		t.Fatal("root path deletion must be rejected")
	}
	status, _ = executeRemote(t, s, remoteCommand("delete_path", map[string]interface{}{"path": "dir one"}))
	if status != 1 {
		t.Fatal("directory deletion failed")
	}
}

func TestRemoteBatchCopyMoveDeleteKeepsSourceAndDoesNotOverwrite(t *testing.T) {
	s := testFileSession(t)
	for _, directory := range []string{"a", "b", "copy-dest", "move-dest"} {
		if err := os.Mkdir(filepath.Join(s.Cwd, directory), 0755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(s.Cwd, "a", "file.txt"), []byte("content"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(s.Cwd, "b", "file.txt"), []byte("original"), 0644); err != nil {
		t.Fatal(err)
	}
	cmd := remoteCommand("paste_paths", map[string]interface{}{"paths": []string{"a/file.txt", "b/file.txt"}, "destination_dir": "copy-dest", "operation": "copy"})
	status, text := executeRemote(t, s, cmd)
	if status != 1 {
		t.Fatal(text)
	}
	result := decodeRemoteResult(t, text)
	if result["status"] != float64(1) || result["total"] != float64(2) || result["succeeded"] != float64(1) || result["failed"] != float64(1) || len(result["errors"].([]interface{})) != 1 {
		t.Fatalf("wrong partial result: %#v", result)
	}
	if data, err := os.ReadFile(filepath.Join(s.Cwd, "copy-dest", "file.txt")); err != nil || !reflect.DeepEqual(data, []byte("content")) {
		t.Fatalf("copy data mismatch %q %v", data, err)
	}
	if _, err := os.Stat(filepath.Join(s.Cwd, "a", "file.txt")); err != nil {
		t.Fatal("copy removed source")
	}
	status, text = executeRemote(t, s, remoteCommand("paste_paths", map[string]interface{}{"paths": []string{"a/file.txt"}, "destination_dir": "move-dest", "operation": "move"}))
	if status != 1 || decodeRemoteResult(t, text)["succeeded"] != float64(1) {
		t.Fatalf("move failed: %d %s", status, text)
	}
	if _, err := os.Stat(filepath.Join(s.Cwd, "a", "file.txt")); !os.IsNotExist(err) {
		t.Fatal("move kept source")
	}
	status, text = executeRemote(t, s, remoteCommand("paste_paths", map[string]interface{}{"paths": []string{"move-dest"}, "destination_dir": "move-dest", "operation": "copy"}))
	if status != 1 || decodeRemoteResult(t, text)["failed"] != float64(1) {
		t.Fatalf("expected batch rejection of directory into itself: %d %s", status, text)
	}
	status, text = executeRemote(t, s, remoteCommand("delete_paths", map[string]interface{}{"paths": []string{"move-dest/file.txt", "missing"}}))
	if status != 1 || decodeRemoteResult(t, text)["failed"] != float64(1) {
		t.Fatalf("expected partial deletion: %d %s", status, text)
	}
}

func TestRemoteCommandsAdvertisedInManifestButNotSuggest(t *testing.T) {
	want := map[string]bool{"browse_dir": false, "mkdir_path": false, "rename_path": false, "delete_path": false, "delete_paths": false, "paste_paths": false}
	for _, spec := range AllCommands() {
		if _, ok := want[spec.Name]; ok {
			if spec.Suggest || spec.Group != "file_path" {
				t.Fatalf("wrong command contract for %s: %#v", spec.Name, spec)
			}
			delete(want, spec.Name)
		}
	}
	if len(want) != 0 {
		t.Fatalf("missing commands: %#v", want)
	}
}

func TestRemoteDeleteSymlinkDoesNotFollowOutsideDirectory(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink creation requires Windows privilege")
	}
	s := testFileSession(t)
	outside := t.TempDir()
	keep := filepath.Join(outside, "keep.txt")
	if err := os.WriteFile(keep, []byte("important"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(s.Cwd, "shortcut")); err != nil {
		t.Fatal(err)
	}
	status, text := executeRemote(t, s, remoteCommand("delete_path", map[string]interface{}{"path": "shortcut"}))
	if status != 1 {
		t.Fatalf("failed to remove symlink: %s", text)
	}
	if _, err := os.Stat(keep); err != nil {
		t.Fatalf("deleting symlink damaged its target: %v", err)
	}
}

func TestRemotePasteRejectsDirectoryIntoItsSubdirectory(t *testing.T) {
	s := testFileSession(t)
	if err := os.MkdirAll(filepath.Join(s.Cwd, "source", "child"), 0700); err != nil {
		t.Fatal(err)
	}
	_, text := executeRemote(t, s, remoteCommand("paste_paths", map[string]interface{}{
		"paths": []string{"source"}, "destination_dir": "source/child", "operation": "copy",
	}))
	result := decodeRemoteResult(t, text)
	if result["failed"] != float64(1) || result["succeeded"] != float64(0) || result["status"] != float64(0) {
		t.Fatalf("nested copy should be rejected: %#v", result)
	}
	if _, err := os.Stat(filepath.Join(s.Cwd, "source", "child", "source")); !os.IsNotExist(err) {
		t.Fatal("nested destination was created")
	}
}
