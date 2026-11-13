package executor

import (
	"archive/zip"
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestRemoteZipSelectedFileAndImplicitDirectory(t *testing.T) {
	session := testFileSession(t)
	archivePath := filepath.Join(session.Cwd, "picked.zip")
	output, err := os.Create(archivePath)
	if err != nil {
		t.Fatal(err)
	}
	writer := zip.NewWriter(output)
	bytes := make([]byte, 3*1024*1024)
	for i := range bytes {
		bytes[i] = byte(i)
	}
	for name, contents := range map[string][]byte{
		"root/a.bin": bytes, "root/sub/b.txt": []byte("B"), "root/skip.txt": []byte("skip"),
	} {
		item, err := writer.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := item.Write(contents); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err := output.Close(); err != nil {
		t.Fatal(err)
	}
	dest := filepath.Join(session.Cwd, "dest")
	if err := os.Mkdir(dest, 0755); err != nil {
		t.Fatal(err)
	}
	status, text := executeRemote(t, session, remoteRequest("extract_archive", map[string]interface{}{
		"path": archivePath, "destination_dir": dest, "entry_name": "root/a.bin",
	}))
	if status != 1 {
		t.Fatalf("selected binary failed: %s", text)
	}
	got, err := os.ReadFile(filepath.Join(dest, "a.bin"))
	if err != nil || len(got) != len(bytes) || got[1048576] != bytes[1048576] {
		t.Fatal("binary entry truncated")
	}
	if _, err := os.Stat(filepath.Join(dest, "root")); !os.IsNotExist(err) {
		t.Fatalf("extracted ancestors: %v", err)
	}
	if status, _ := executeRemote(t, session, remoteRequest("extract_archive", map[string]interface{}{
		"path": archivePath, "destination_dir": dest, "entry_name": "root/a.bin",
	})); status != 0 {
		t.Fatal("overwrote existing selected file")
	}
	status, text = executeRemote(t, session, remoteRequest("extract_archive", map[string]interface{}{
		"path": archivePath, "destination_dir": dest, "entry_name": "root/sub",
	}))
	if status != 1 {
		t.Fatalf("selected directory failed: %s", text)
	}
	child, err := os.ReadFile(filepath.Join(dest, "sub", "b.txt"))
	if err != nil || string(child) != "B" {
		t.Fatalf("selected directory incorrect: %q %v", child, err)
	}
	if _, err := os.Stat(filepath.Join(dest, "skip.txt")); !os.IsNotExist(err) {
		t.Fatalf("extracted sibling: %v", err)
	}
	for _, value := range []string{"../escape", "missing", "root/../../escape"} {
		if result, err := extractRemoteZipEntry(context.Background(), archivePath, dest, value); err == nil {
			t.Fatalf("unsafe or missing selection accepted %q: %v", value, result)
		}
	}
}
