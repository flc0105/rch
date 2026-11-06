package executor

import (
	"archive/zip"
	"context"
	"encoding/binary"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRemoteSaveTextPreservesEncodingAndRejectsBinary(t *testing.T) {
	session := testFileSession(t)
	utf8Path := filepath.Join(session.Cwd, "note.data")
	if err := os.WriteFile(utf8Path, []byte("hello"), 0600); err != nil {
		t.Fatal(err)
	}
	status, output := executeRemote(t, session, remoteCommand("save_file_content", map[string]interface{}{
		"path": utf8Path, "content": "保存中文", "encoding": "utf-8",
	}))
	if status != 1 {
		t.Fatalf("UTF-8 save failed: %s", output)
	}
	b, err := os.ReadFile(utf8Path)
	if err != nil || string(b) != "保存中文" {
		t.Fatalf("UTF-8 bytes incorrect: %q %v", b, err)
	}

	utf16Path := filepath.Join(session.Cwd, "utf16.data")
	utf16, err := encodeRemoteText("旧内容", "utf-16-le")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(utf16Path, utf16, 0600); err != nil {
		t.Fatal(err)
	}
	status, output = executeRemote(t, session, remoteCommand("save_file_content", map[string]interface{}{
		"path": utf16Path, "content": "新😊行", "encoding": "utf-16-le",
	}))
	if status != 1 {
		t.Fatalf("UTF-16 save failed: %s", output)
	}
	got, err := os.ReadFile(utf16Path)
	if err != nil {
		t.Fatal(err)
	}
	text, codec, err := decodeRemoteText(got)
	if err != nil || text != "新😊行" || codec != "utf-16-le" || binary.LittleEndian.Uint16(got[:2]) != 0xfeff {
		t.Fatalf("lost UTF-16 encoding: %q %s %v", text, codec, err)
	}
	if status, _ = executeRemote(t, session, remoteCommand("save_file_content", map[string]interface{}{
		"path": utf16Path, "content": "incorrect", "encoding": "utf-8",
	})); status != 0 {
		t.Fatal("mismatched codec was accepted")
	}
	binaryPath := filepath.Join(session.Cwd, "binary.txt")
	if err := os.WriteFile(binaryPath, []byte{0, 1, 2, 3}, 0600); err != nil {
		t.Fatal(err)
	}
	if status, _ = executeRemote(t, session, remoteCommand("save_file_content", map[string]interface{}{
		"path": binaryPath, "content": "text", "encoding": "utf-8",
	})); status != 0 {
		t.Fatal("binary file became editable")
	}
	if b, err := os.ReadFile(binaryPath); err != nil || len(b) != 4 || b[0] != 0 {
		t.Fatalf("binary file changed: %v %v", b, err)
	}
}

func TestRemoteZipPreviewEntryCreateAndExtract(t *testing.T) {
	session := testFileSession(t)
	from := filepath.Join(session.Cwd, "folder")
	if err := os.MkdirAll(filepath.Join(from, "nested"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(from, "nested", "note.txt"), []byte("zip 中文"), 0600); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(session.Cwd, "archives")
	if err := os.Mkdir(target, 0755); err != nil {
		t.Fatal(err)
	}
	status, out := executeRemote(t, session, remoteCommand("create_zip_paths", map[string]interface{}{
		"paths": []string{from}, "destination_dir": target, "archive_name": "my archive.zip",
	}))
	if status != 1 {
		t.Fatalf("create zip: %s", out)
	}
	created := decodeRemoteResult(t, out)
	zipPath := filepath.Join(target, "my archive.zip")
	if created["archive_path"] != zipPath {
		t.Fatalf("unexpected ZIP name: %#v", created)
	}
	if status, _ = executeRemote(t, session, remoteCommand("create_zip_paths", map[string]interface{}{
		"paths": []string{from}, "destination_dir": target, "archive_name": "my archive.zip",
	})); status != 0 {
		t.Fatal("ZIP creation overwrote existing file")
	}
	status, out = executeRemote(t, session, remoteCommand("peek_zip", map[string]interface{}{"path": zipPath}))
	if status != 1 {
		t.Fatalf("ZIP peek failed: %s", out)
	}
	peek := decodeRemoteResult(t, out)
	if peek["file_count"] != float64(1) || peek["name"] != "my archive.zip" {
		t.Fatalf("incorrect ZIP tree summary: %#v", peek)
	}
	tree := peek["tree"].([]interface{})
	if tree[0].(map[string]interface{})["name"] != "folder" {
		t.Fatalf("wrong root ZIP entry: %#v", tree)
	}
	status, out = executeRemote(t, session, remoteCommand("read_zip_entry", map[string]interface{}{
		"path": zipPath, "entry_name": "folder/nested/note.txt",
	}))
	if status != 1 {
		t.Fatalf("ZIP entry failed: %s", out)
	}
	entry := decodeRemoteResult(t, out)
	if entry["type"] != "text" || entry["content"] != "zip 中文" {
		t.Fatalf("incorrect ZIP preview: %#v", entry)
	}
	extracted := filepath.Join(session.Cwd, "extracted")
	if err := os.Mkdir(extracted, 0755); err != nil {
		t.Fatal(err)
	}
	status, out = executeRemote(t, session, remoteCommand("extract_zip_path", map[string]interface{}{
		"path": zipPath, "destination_dir": extracted,
	}))
	if status != 1 {
		t.Fatalf("ZIP extraction failed: %s", out)
	}
	result := decodeRemoteResult(t, out)
	if result["mode"] != "single_root" {
		t.Fatalf("unexpected ZIP extract mode: %#v", result)
	}
	data, err := os.ReadFile(filepath.Join(extracted, "folder", "nested", "note.txt"))
	if err != nil || string(data) != "zip 中文" {
		t.Fatalf("bad extracted file: %q %v", data, err)
	}
}

func TestZipExtractionRejectsTraversalAndDoesNotWriteOutside(t *testing.T) {
	session := testFileSession(t)
	zipPath := filepath.Join(session.Cwd, "traversal.zip")
	out, err := os.Create(zipPath)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(out)
	w, err := zw.Create("../escape.txt")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = w.Write([]byte("escaped"))
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := out.Close(); err != nil {
		t.Fatal(err)
	}
	dest := filepath.Join(session.Cwd, "destination")
	if err := os.Mkdir(dest, 0755); err != nil {
		t.Fatal(err)
	}
	if status, _ := executeRemote(t, session, remoteCommand("peek_zip", map[string]interface{}{"path": zipPath})); status != 0 {
		t.Fatal("unsafe ZIP tree was accepted")
	}
	if status, _ := executeRemote(t, session, remoteCommand("extract_zip_path", map[string]interface{}{
		"path": zipPath, "destination_dir": dest,
	})); status != 0 {
		t.Fatal("ZIP traversal extraction accepted")
	}
	if _, err := os.Stat(filepath.Join(session.Cwd, "escape.txt")); !os.IsNotExist(err) {
		t.Fatalf("path traversal created file: %v", err)
	}
	if dir, err := os.ReadDir(dest); err != nil || len(dir) != 0 {
		t.Fatalf("failed ZIP left extraction data: %v %v", dir, err)
	}
	if _, err := safeZipEntry("C:\\escape.txt"); err == nil {
		t.Fatal("drive-qualified ZIP path accepted")
	}
	if _, err := safeZipEntry("sub/../escape"); err == nil {
		t.Fatal("parent traversal ZIP path accepted")
	}
}

func TestZipBinaryEntryIsNotPresentedAsEditableText(t *testing.T) {
	session := testFileSession(t)
	zipPath := filepath.Join(session.Cwd, "binary.zip")
	f, err := os.Create(zipPath)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(f)
	w, err := zw.Create("thing.txt")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = w.Write([]byte{0, 1, 2, 3})
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	status, text := executeRemote(t, session, remoteCommand("read_zip_entry", map[string]interface{}{"path": zipPath, "entry_name": "thing.txt"}))
	if status != 1 {
		t.Fatal(text)
	}
	data := decodeRemoteResult(t, text)
	if data["type"] != "binary" || data["content"] != "" || !strings.Contains(data["message"].(string), "Binary") {
		t.Fatalf("binary displayed as text: %#v", data)
	}
}

func TestZipSelectedPathsWithSameNameAndFailureCleanup(t *testing.T) {
	base := t.TempDir()
	first := filepath.Join(base, "first")
	second := filepath.Join(base, "second")
	for _, dir := range []string{first, second} {
		if err := os.Mkdir(dir, 0755); err != nil {
			t.Fatal(err)
		}
	}
	pathA := filepath.Join(first, "same.txt")
	pathB := filepath.Join(second, "same.txt")
	if err := os.WriteFile(pathA, []byte("A"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(pathB, []byte("B"), 0600); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(base, "both.zip")
	if err := writeZipPaths(context.Background(), target, []string{pathA, pathB}); err != nil {
		t.Fatal(err)
	}
	archive, err := zip.OpenReader(target)
	if err != nil {
		t.Fatal(err)
	}
	defer archive.Close()
	if len(archive.File) != 2 || archive.File[0].Name != "same.txt" || archive.File[1].Name != "same.txt_1" {
		t.Fatalf("duplicate source names were not kept distinct: %#v", archive.File)
	}
	missing := filepath.Join(base, "missing.txt")
	partial := filepath.Join(base, "incomplete.zip")
	if err := writeZipPaths(context.Background(), partial, []string{pathA, missing}); err == nil {
		t.Fatal("expected ZIP source error")
	}
	if _, err := os.Lstat(partial); !os.IsNotExist(err) {
		t.Fatalf("failed ZIP left a partial file: %v", err)
	}
}
