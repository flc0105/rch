package executor

import (
	"archive/zip"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeConflictTestFile(t *testing.T, name, value string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(name), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(name, []byte(value), 0644); err != nil {
		t.Fatal(err)
	}
}
func readConflictTestFile(t *testing.T, name string) string {
	t.Helper()
	v, err := os.ReadFile(name)
	if err != nil {
		t.Fatal(err)
	}
	return string(v)
}
func TestConflictFileStopReplaceAndKeepBoth(t *testing.T) {
	root := t.TempDir()
	src := filepath.Join(root, "src", "file.txt")
	dst := filepath.Join(root, "dst", "file.txt")
	writeConflictTestFile(t, src, "NEW")
	writeConflictTestFile(t, dst, "OLD")
	if err := applyRemoteConflict(context.Background(), src, dst, "copy", "stop"); err == nil {
		t.Fatal("stop overwrote file")
	}
	if err := applyRemoteConflict(context.Background(), src, dst, "copy", "keep_both"); err != nil {
		t.Fatal(err)
	}
	if readConflictTestFile(t, dst) != "OLD" {
		t.Fatal("existing file overwritten")
	}
	entries, err := os.ReadDir(filepath.Dir(dst))
	if err != nil || len(entries) != 2 {
		t.Fatalf("keep both: %v %v", entries, err)
	}
	found := false
	for _, entry := range entries {
		if entry.Name() != "file.txt" && strings.HasPrefix(entry.Name(), "file_20") && strings.HasSuffix(entry.Name(), ".txt") {
			found = true
		}
	}
	if !found {
		t.Fatal("no timestamp+hash distinct name")
	}
	if err := applyRemoteConflict(context.Background(), src, dst, "copy", "replace"); err != nil {
		t.Fatal(err)
	}
	if readConflictTestFile(t, dst) != "NEW" {
		t.Fatal("replacement did not happen")
	}
}
func TestConflictDirectoryMergeAndReplace(t *testing.T) {
	root := t.TempDir()
	src := filepath.Join(root, "a", "dir")
	dst := filepath.Join(root, "b", "dir")
	writeConflictTestFile(t, filepath.Join(src, "shared"), "new")
	writeConflictTestFile(t, filepath.Join(dst, "shared"), "old")
	writeConflictTestFile(t, filepath.Join(dst, "untouched"), "stay")
	if err := applyRemoteConflict(context.Background(), src, dst, "copy", "merge"); err != nil {
		t.Fatal(err)
	}
	if readConflictTestFile(t, filepath.Join(dst, "shared")) != "new" || readConflictTestFile(t, filepath.Join(dst, "untouched")) != "stay" {
		t.Fatal("merge destroyed old-only data")
	}
	if err := applyRemoteConflict(context.Background(), src, dst, "copy", "replace"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(filepath.Join(dst, "untouched")); !os.IsNotExist(err) {
		t.Fatal("replacement should remove destination-only entries")
	}
}
func TestConflictMixedTypesAndUploadCommit(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "source")
	folder := filepath.Join(root, "dest")
	writeConflictTestFile(t, source, "data")
	if err := os.Mkdir(folder, 0755); err != nil {
		t.Fatal(err)
	}
	if err := applyRemoteConflict(context.Background(), source, folder, "copy", "replace"); err == nil {
		t.Fatal("file replaced directory")
	}
	if err := applyRemoteConflict(context.Background(), source, folder, "copy", "keep_both"); err != nil {
		t.Fatal(err)
	}
	incoming := filepath.Join(root, "temp")
	dst := filepath.Join(root, "upload.txt")
	writeConflictTestFile(t, incoming, "new")
	writeConflictTestFile(t, dst, "old")
	if err := stageRemoteTransferFile(context.Background(), incoming, dst, "stop"); err == nil {
		t.Fatal("stop overwrote upload")
	}
	if err := stageRemoteTransferFile(context.Background(), incoming, dst, "keep_both"); err != nil {
		t.Fatal(err)
	}
	if readConflictTestFile(t, dst) != "old" {
		t.Fatal("upload overwritten")
	}
	if err := stageRemoteTransferFile(context.Background(), incoming, dst, "replace"); err != nil {
		t.Fatal(err)
	}
	if readConflictTestFile(t, dst) != "new" {
		t.Fatal("replacement upload failed")
	}
}
func TestConflictPasteInspectDoesNotWriteAndKeepsNames(t *testing.T) {
	s := testFileSession(t)
	src := filepath.Join(s.Cwd, "a.txt")
	targetDir := filepath.Join(s.Cwd, "target")
	writeConflictTestFile(t, src, "NEW")
	writeConflictTestFile(t, filepath.Join(targetDir, "a.txt"), "OLD")
	status, text := executeRemote(t, s, remoteCommand("paste_paths", map[string]interface{}{"paths": []string{src}, "destination_dir": targetDir, "operation": "copy", "inspect": true}))
	if status != 1 {
		t.Fatal(text)
	}
	var inspect struct {
		Conflicts []map[string]interface{} `json:"conflicts"`
	}
	if err := json.Unmarshal([]byte(text), &inspect); err != nil || len(inspect.Conflicts) != 1 {
		t.Fatalf("inspect: %v %v", inspect, err)
	}
	if readConflictTestFile(t, filepath.Join(targetDir, "a.txt")) != "OLD" {
		t.Fatal("inspect mutated target")
	}
	status, text = executeRemote(t, s, remoteCommand("paste_paths", map[string]interface{}{"paths": []string{src}, "destination_dir": targetDir, "operation": "copy", "conflict_policies": []string{"keep_both"}}))
	if status != 1 {
		t.Fatal(text)
	}
	entries, _ := os.ReadDir(targetDir)
	if len(entries) != 2 {
		t.Fatalf("expected both names: %v", entries)
	}
}

func TestConflictZipSelectedMergeReplaceAndInspect(t *testing.T) {
	s := testFileSession(t)
	archivePath := filepath.Join(s.Cwd, "archive.zip")
	writerFile, err := os.Create(archivePath)
	if err != nil {
		t.Fatal(err)
	}
	zipper := zip.NewWriter(writerFile)
	for name, contents := range map[string]string{"root/shared": "NEW", "root/additional": "NEW"} {
		entry, err := zipper.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := entry.Write([]byte(contents)); err != nil {
			t.Fatal(err)
		}
	}
	if err := zipper.Close(); err != nil {
		t.Fatal(err)
	}
	if err := writerFile.Close(); err != nil {
		t.Fatal(err)
	}
	destination := filepath.Join(s.Cwd, "dest")
	writeConflictTestFile(t, filepath.Join(destination, "root", "shared"), "OLD")
	writeConflictTestFile(t, filepath.Join(destination, "root", "left"), "STAY")
	inspect := map[string]interface{}{"path": archivePath, "destination_dir": destination, "inspect": true}
	status, text := executeRemote(t, s, remoteCommand("extract_zip_path", inspect))
	if status != 1 {
		t.Fatal(text)
	}
	var report struct {
		Conflicts []map[string]interface{} `json:"conflicts"`
	}
	if err := json.Unmarshal([]byte(text), &report); err != nil || len(report.Conflicts) != 1 {
		t.Fatalf("bad inspection: %s %v", text, err)
	}
	if readConflictTestFile(t, filepath.Join(destination, "root", "shared")) != "OLD" {
		t.Fatal("inspect modified target")
	}
	for _, policy := range []string{"merge", "replace"} {
		status, text = executeRemote(t, s, remoteCommand("extract_zip_path", map[string]interface{}{"path": archivePath, "destination_dir": destination, "conflict_policy": policy}))
		if status != 1 {
			t.Fatalf("%s: %s", policy, text)
		}
		if readConflictTestFile(t, filepath.Join(destination, "root", "shared")) != "NEW" {
			t.Fatal("file not replaced")
		}
		_, err := os.Stat(filepath.Join(destination, "root", "left"))
		if policy == "merge" && err != nil {
			t.Fatal("merge lost target-only file")
		}
		if policy == "replace" && !os.IsNotExist(err) {
			t.Fatal("replace kept target-only file")
		}
	}
}

func TestConflictCopyIntoSameDirectoryKeepBoth(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "note.txt")
	writeConflictTestFile(t, source, "ORIGINAL")
	if err := applyRemoteConflict(context.Background(), source, source, "copy", "keep_both"); err != nil {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 2 {
		t.Fatalf("expected two files: %v %v", entries, err)
	}
	if readConflictTestFile(t, source) != "ORIGINAL" {
		t.Fatal("original changed")
	}
}

func TestUploadConflictPolicyValidation(t *testing.T) {
	target := filepath.Join(t.TempDir(), "upload.txt")
	for _, policy := range []string{"merge", "skip", ""} {
		if validRemoteUploadPolicy(policy) {
			t.Fatalf("unexpected policy accepted: %q", policy)
		}
		if err := stageRemoteTransferFile(context.Background(), "unused-staged", target, policy); err == nil {
			t.Fatalf("invalid policy should reject: %q", policy)
		}
		if _, err := os.Stat(target); !os.IsNotExist(err) {
			t.Fatalf("invalid policy wrote target: %v", err)
		}
	}
	for _, policy := range []string{"stop", "replace", "keep_both"} {
		if !validRemoteUploadPolicy(policy) {
			t.Fatalf("valid policy rejected: %q", policy)
		}
	}
}
