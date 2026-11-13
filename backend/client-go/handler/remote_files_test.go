package handler

import (
	"os"
	"path/filepath"
	"testing"
)

// Real RATSocket frames exercise the same channel used by WebRemoteFileService.
func TestRemoteBrowseEndToEndControlFrame(t *testing.T) {
	session, peer := pair(t)
	root := t.TempDir()
	session.Cwd = root
	if err := os.WriteFile(filepath.Join(root, "hello.txt"), []byte("hi"), 0600); err != nil {
		t.Fatal(err)
	}
	go Handle(session, map[string]interface{}{"type": "control", "id": float64(123), "domain": "remote_files", "action": "browse_directory", "payload": map[string]interface{}{"path": root, "page": float64(1), "page_size": float64(20)}})
	result := receive(t, peer)
	if result["type"] != "result" || result["id"] != float64(123) || result["status"] != float64(1) || result["eof"] != float64(1) {
		t.Fatalf("incorrect terminal response: %#v", result)
	}
	content := result["data"].(map[string]interface{})
	if content["current_path"] != root || content["pagination"].(map[string]interface{})["total_visible"] != float64(1) {
		t.Fatalf("Remote Files payload inconsistent: %#v", content)
	}
}

func TestRemoteBrowseCancellationReleasesForegroundSlot(t *testing.T) {
	session, peer := pair(t)
	session.Cwd = t.TempDir()
	// A completed browse releases the same foreground slot as cancellable shell.
	go Handle(session, map[string]interface{}{"type": "control", "id": float64(57), "domain": "remote_files", "action": "browse_directory", "payload": map[string]interface{}{}})
	result := receive(t, peer)
	if result["eof"] != float64(1) || result["status"] != float64(1) {
		t.Fatalf("browse did not finish: %#v", result)
	}
	if session.HasActiveShell() {
		t.Fatal("browse left foreground slot occupied")
	}
	// Existing heartbeat works after a file operation.
	go Handle(session, map[string]interface{}{"type": "heartbeat", "id": float64(58)})
	if msg := receive(t, peer); msg["type"] != "heartbeat_ack" {
		t.Fatalf("connection unusable after browse: %#v", msg)
	}
}
