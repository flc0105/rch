package executor

import (
	"bytes"
	"context"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"client-go/protocol"
)

func TestInlineCommandTCPRegistrationAndArtifactMetadata(t *testing.T) {
	data := bytes.Repeat([]byte("upload from command"), 100)
	name := filepath.Join(t.TempDir(), "命令.txt")
	if err := os.WriteFile(name, data, 0600); err != nil {
		t.Fatal(err)
	}
	primary, remote := net.Pipe()
	defer primary.Close()
	defer remote.Close()
	s := NewSession(protocol.NewRATSocket(primary), "client")
	s.CurrentCommandID = 42
	s.SetSessionToken("current-token")
	sent := make(chan error, 1)
	s.SetFileDataOpener(func(_ context.Context, id, token string, _ func()) (net.Conn, error) {
		if token != "current-token" {
			return nil, fmt.Errorf("token mismatch")
		}
		left, right := net.Pipe()
		go func() {
			defer right.Close()
			if err := writeFileControl(right, map[string]interface{}{"ok": true}); err != nil {
				sent <- err
				return
			}
			hdr, err := receiveFileControl(right)
			if err != nil {
				sent <- err
				return
			}
			output, err := os.CreateTemp(t.TempDir(), "inline-")
			if err != nil {
				sent <- err
				return
			}
			defer output.Close()
			_, err = receiveTCPFile(context.Background(), right, output, hdr, nil)
			if err != nil {
				sent <- err
				return
			}
			b, err := os.ReadFile(output.Name())
			if err != nil || !bytes.Equal(data, b) || hdr["category"] != "downloads" {
				sent <- fmt.Errorf("inline content mismatch")
				return
			}
			sent <- writeFileControl(right, map[string]interface{}{"ok": true, "data": map[string]interface{}{"artifact_id": "art-inline", "original_name": "命令.txt"}})
		}()
		return left, nil
	})
	type outcome struct {
		payload map[string]interface{}
		err     error
	}
	done := make(chan outcome, 1)
	go func() { p, e := s.uploadCommandFileTCP(name, "downloads"); done <- outcome{p, e} }()
	peer := protocol.NewRATSocket(remote)
	req, err := peer.Recv()
	if err != nil {
		t.Fatal(err)
	}
	id, _ := req["transfer_id"].(string)
	if req["type"] != "transfer_register" || req["file_transfer_mode"] != "tcp_streaming" || req["direction"] != "client_to_server" || req["command_id"] != float64(42) || len(id) != 32 {
		t.Fatalf("invalid inline registration: %#v", req)
	}
	s.AcceptTransferRegistration(map[string]interface{}{"transfer_id": id, "accepted": true})
	for {
		_ = remote.SetReadDeadline(time.Now().Add(3 * time.Second))
		update, err := peer.Recv()
		if err != nil {
			t.Fatal(err)
		}
		if update["type"] != "transfer_update" {
			t.Fatalf("invalid update: %v", update)
		}
		if update["state"] == "completed" {
			break
		}
	}
	if e := <-sent; e != nil {
		t.Fatal(e)
	}
	select {
	case outcome := <-done:
		if outcome.err != nil {
			t.Fatal(outcome.err)
		}
		payload, _ := outcome.payload["data"].(map[string]interface{})
		if payload["artifact_id"] != "art-inline" {
			t.Fatalf("lost Artifact ID: %#v", outcome.payload)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("inline transfer did not finish")
	}
}
