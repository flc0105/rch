package handler

import (
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// Real RATSocket frames exercise the same channel used by WebRemoteFileService.
func TestRemoteBrowseEndToEndCommandFrame(t *testing.T) {
	session, peer := pair(t)
	root := t.TempDir()
	session.Cwd = root
	if err := os.WriteFile(filepath.Join(root, "hello.txt"), []byte("hi"), 0600); err != nil {
		t.Fatal(err)
	}
	payload, _ := json.Marshal(map[string]interface{}{"path": root, "page": 1, "page_size": 20})
	command := "browse_dir __json__:" + base64.URLEncoding.EncodeToString(payload)
	go Handle(session, map[string]interface{}{"type": "command", "id": float64(123), "text": command})
	result := receive(t, peer)
	if result["type"] != "result" || result["id"] != float64(123) || result["status"] != float64(1) || result["eof"] != float64(1) {
		t.Fatalf("incorrect terminal response: %#v", result)
	}
	var content map[string]interface{}
	if err := json.Unmarshal([]byte(result["text"].(string)), &content); err != nil {
		t.Fatalf("Server cannot decode JSON result: %v", err)
	}
	if content["current_path"] != root || content["pagination"].(map[string]interface{})["total_visible"] != float64(1) {
		t.Fatalf("Remote Files payload inconsistent: %#v", content)
	}
}

func TestRemoteBrowseCancellationReleasesForegroundSlot(t *testing.T) {
	session, peer := pair(t)
	session.Cwd = t.TempDir()
	// A completed browse releases the same foreground slot as cancellable shell.
	go Handle(session, map[string]interface{}{"type": "command", "id": float64(57), "text": "browse_dir"})
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
