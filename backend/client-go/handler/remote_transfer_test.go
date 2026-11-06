package handler

import (
	"archive/zip"
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"testing"
	"time"

	"client-go/config"
)

func waitTransfer(t *testing.T, peerMessage func() map[string]interface{}) []map[string]interface{} {
	t.Helper()
	updates := make([]map[string]interface{}, 0)
	for i := 0; i < 30; i++ {
		update := peerMessage()
		if update["type"] != "transfer_update" {
			t.Fatalf("not a transfer update: %#v", update)
		}
		updates = append(updates, update)
		if update["state"] == "completed" || update["state"] == "failed" || update["state"] == "cancelled" {
			return updates
		}
	}
	t.Fatal("missing terminal Transfer update")
	return nil
}

func TestRemoteTransferDownloadAndRawPreviewUpload(t *testing.T) {
	raw := []byte{0x89, 'P', 'N', 'G', 0x0d, 0x0a, 0x1a, 0x0a, 0x01, 0x02, 0x03, 0x04}
	var mu sync.Mutex
	received := make([]struct {
		typ, category, filename string
		data                    []byte
	}, 0)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/files/upload" || r.Method != http.MethodPost {
			http.Error(w, "unexpected route", 404)
			return
		}
		part, err := r.MultipartReader()
		if err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		fields := map[string]string{}
		var filename string
		var data []byte
		for {
			item, err := part.NextPart()
			if err == io.EOF {
				break
			}
			if err != nil {
				http.Error(w, err.Error(), 400)
				return
			}
			b, err := io.ReadAll(item)
			if err != nil {
				http.Error(w, err.Error(), 400)
				return
			}
			if item.FormName() == "file" {
				filename = item.FileName()
				data = b
			} else {
				fields[item.FormName()] = string(b)
			}
		}
		mu.Lock()
		received = append(received, struct {
			typ, category, filename string
			data                    []byte
		}{fields["artifact_type"], fields["category"], filename, data})
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"code":0,"data":{"artifact_id":"artifact-abc"}}`))
	}))
	defer server.Close()
	old := config.UPLOAD_BASE_URL
	config.UPLOAD_BASE_URL = server.URL
	defer func() { config.UPLOAD_BASE_URL = old }()

	session, peer := pair(t)
	session.Cwd = t.TempDir()
	imagePath := filepath.Join(session.Cwd, "原始图片.png")
	if err := os.WriteFile(imagePath, raw, 0600); err != nil {
		t.Fatal(err)
	}
	for _, job := range []struct{ operation, typ, category string }{
		{"client_to_server_file", "files", "download"},
		{"client_to_server_preview", "previews", "preview_cache"},
	} {
		Handle(session, map[string]interface{}{"type": "transfer_start", "transfer_id": job.operation, "operation": job.operation, "payload": map[string]interface{}{"path": imagePath}})
		updates := waitTransfer(t, func() map[string]interface{} { return receive(t, peer) })
		final := updates[len(updates)-1]
		if final["state"] != "completed" || final["artifact_id"] != "artifact-abc" || final["total_bytes"] != float64(len(raw)) {
			t.Fatalf("wrong terminal update: %#v", final)
		}
	}
	mu.Lock()
	defer mu.Unlock()
	if len(received) != 2 {
		t.Fatalf("unexpected upload count: %d", len(received))
	}
	for idx, item := range received {
		if item.typ != []string{"files", "previews"}[idx] || item.category != []string{"download", "preview_cache"}[idx] || item.filename != "原始图片.png" || !bytes.Equal(item.data, raw) {
			t.Errorf("upload changed file or metadata: %#v", item)
		}
	}
	session.CloseTransfers()
}

func TestBrowserUploadToClientAndNoOverwrite(t *testing.T) {
	contents := []byte("Hello 远程文件 uploaded from browser\n")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/upload-tmp/staged/sample" {
			http.Error(w, "not found", 404)
			return
		}
		w.Header().Set("Content-Length", strconv.Itoa(len(contents)))
		_, _ = w.Write(contents)
	}))
	defer server.Close()
	old := config.UPLOAD_BASE_URL
	config.UPLOAD_BASE_URL = server.URL
	defer func() { config.UPLOAD_BASE_URL = old }()
	session, peer := pair(t)
	session.Cwd = t.TempDir()
	dest := filepath.Join(session.Cwd, "uploads")
	payload := map[string]interface{}{"relative_url": "/api/upload-tmp/staged/sample", "filename": "上传.txt", "save_dir": dest}
	Handle(session, map[string]interface{}{"type": "transfer_start", "transfer_id": "upload-one", "operation": "server_to_client_file", "payload": payload})
	updates := waitTransfer(t, func() map[string]interface{} { return receive(t, peer) })
	if updates[len(updates)-1]["state"] != "completed" {
		t.Fatalf("download failed: %#v", updates)
	}
	data, err := os.ReadFile(filepath.Join(dest, "上传.txt"))
	if err != nil || !bytes.Equal(data, contents) {
		t.Fatalf("uploaded contents mismatch: %q %v", data, err)
	}
	Handle(session, map[string]interface{}{"type": "transfer_start", "transfer_id": "upload-two", "operation": "server_to_client_file", "payload": payload})
	updates = waitTransfer(t, func() map[string]interface{} { return receive(t, peer) })
	if updates[len(updates)-1]["state"] != "failed" {
		t.Fatalf("overwrote existing file: %#v", updates)
	}
	entries, err := os.ReadDir(dest)
	if err != nil || len(entries) != 1 {
		t.Fatalf("unexpected temp or overwritten files: %#v %v", entries, err)
	}
	session.CloseTransfers()
}

func TestTransferCancelDoesNotWritePartialFile(t *testing.T) {
	started := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(started)
		<-r.Context().Done()
	}))
	defer server.Close()
	old := config.UPLOAD_BASE_URL
	config.UPLOAD_BASE_URL = server.URL
	defer func() { config.UPLOAD_BASE_URL = old }()
	session, peer := pair(t)
	session.Cwd = t.TempDir()
	destination := filepath.Join(session.Cwd, "dest")
	Handle(session, map[string]interface{}{"type": "transfer_start", "transfer_id": "cancel-1", "operation": "server_to_client_file", "payload": map[string]interface{}{"relative_url": "/blocking", "filename": "pending.bin", "save_dir": destination}})
	// Drain the first running update before cancelling so net.Pipe cannot block.
	first := receive(t, peer)
	if first["state"] != "running" {
		t.Fatalf("wrong first update: %#v", first)
	}
	// Drain the transfer's staging progress before waiting for HTTP to start.
	stage := receive(t, peer)
	if stage["state"] != "running" || stage["stage"] != "transferring" {
		t.Fatalf("unexpected staging update: %#v", stage)
	}
	select {
	case <-started:
	case <-time.After(2 * time.Second):
		t.Fatal("HTTP request never started")
	}
	Handle(session, map[string]interface{}{"type": "transfer_cancel", "transfer_id": "cancel-1"})
	updates := waitTransfer(t, func() map[string]interface{} { return receive(t, peer) })
	if updates[len(updates)-1]["state"] != "cancelled" {
		t.Fatalf("cancel did not finish: %#v", updates)
	}
	if _, err := os.Lstat(filepath.Join(destination, "pending.bin")); !os.IsNotExist(err) {
		t.Fatalf("partial final file remained: %v", err)
	}
	session.CloseTransfers()
}

func TestRemoteMultiFileZipTransferPreservesBothFiles(t *testing.T) {
	folder := t.TempDir()
	for _, name := range []string{"a.txt", "b.txt"} {
		if err := os.WriteFile(filepath.Join(folder, name), []byte("content:"+name), 0600); err != nil {
			t.Fatal(err)
		}
	}
	var zipBytes []byte
	var uploadedName string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/files/upload" {
			http.Error(w, "not found", 404)
			return
		}
		if err := r.ParseMultipartForm(4096); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		file, header, err := r.FormFile("file")
		if err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		defer file.Close()
		uploadedName = header.Filename
		zipBytes, _ = io.ReadAll(file)
		if r.FormValue("category") != "bundle" || r.FormValue("artifact_type") != "files" {
			http.Error(w, "wrong artifact metadata", 400)
			return
		}
		_, _ = w.Write([]byte(`{"code":0,"data":{"artifact_id":"archive-123"}}`))
	}))
	defer server.Close()
	old := config.UPLOAD_BASE_URL
	config.UPLOAD_BASE_URL = server.URL
	defer func() { config.UPLOAD_BASE_URL = old }()
	session, peer := pair(t)
	session.Cwd = folder
	Handle(session, map[string]interface{}{"type": "transfer_start", "transfer_id": "multi-zip", "operation": "client_to_server_zip", "payload": map[string]interface{}{"paths": []interface{}{filepath.Join(folder, "a.txt"), filepath.Join(folder, "b.txt")}, "archive_name": "backup.zip"}})
	updates := waitTransfer(t, func() map[string]interface{} { return receive(t, peer) })
	if updates[len(updates)-1]["state"] != "completed" || uploadedName != "backup.zip" {
		t.Fatalf("ZIP transfer failed, name=%q updates=%#v", uploadedName, updates)
	}
	archive, err := zip.NewReader(bytes.NewReader(zipBytes), int64(len(zipBytes)))
	if err != nil {
		t.Fatal(err)
	}
	if len(archive.File) != 2 {
		t.Fatalf("unexpected ZIP entries: %d", len(archive.File))
	}
	for _, entry := range archive.File {
		reader, err := entry.Open()
		if err != nil {
			t.Fatal(err)
		}
		data, err := io.ReadAll(reader)
		_ = reader.Close()
		if err != nil || string(data) != "content:"+entry.Name {
			t.Fatalf("wrong ZIP content: %s %q %v", entry.Name, data, err)
		}
	}
	session.CloseTransfers()
}

func TestRemoteTransferRejectedUploadEndsWithFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// The Server may reject before consuming the streaming multipart body.
		http.Error(w, "denied", http.StatusForbidden)
	}))
	defer server.Close()
	old := config.UPLOAD_BASE_URL
	config.UPLOAD_BASE_URL = server.URL
	defer func() { config.UPLOAD_BASE_URL = old }()
	session, peer := pair(t)
	session.Cwd = t.TempDir()
	path := filepath.Join(session.Cwd, "failure.txt")
	if err := os.WriteFile(path, []byte("file"), 0600); err != nil {
		t.Fatal(err)
	}
	Handle(session, map[string]interface{}{"type": "transfer_start", "transfer_id": "denied", "operation": "client_to_server_file", "payload": map[string]interface{}{"path": path}})
	updates := waitTransfer(t, func() map[string]interface{} { return receive(t, peer) })
	if updates[len(updates)-1]["state"] != "failed" {
		t.Fatalf("unexpected response: %#v", updates)
	}
	session.CloseTransfers()
}
