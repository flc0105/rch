package executor

import (
	"context"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"client-go/protocol"
)

func TestSessionEndWaitsForMatchingServerAck(t *testing.T) {
	left, right := net.Pipe()
	defer left.Close()
	defer right.Close()
	session := NewSession(protocol.NewRATSocket(left), "test-id")
	server := protocol.NewRATSocket(right)
	complete := make(chan bool, 1)
	go func() {
		complete <- session.reportSessionEnd("client_restart", "relaunch_instance", time.Second)
	}()
	reported, err := server.Recv()
	if err != nil {
		t.Fatal(err)
	}
	detail, ok := reported["detail"].(map[string]interface{})
	if !ok || detail["command"] != "relaunch_instance" || reported["reason"] != "client_restart" || reported["type"] != "session_end" {
		t.Fatalf("bad report: %#v", reported)
	}
	endID := reported["end_id"]
	if !endIDIsValid(endID) {
		t.Fatalf("bad end_id: %v", endID)
	}
	if err := server.Send(map[string]interface{}{"type": "session_end_ack", "end_id": "wrong"}); err != nil {
		t.Fatal(err)
	}
	select {
	case <-complete:
		t.Fatal("unrelated ack was accepted")
	default:
	}
	if err := server.Send(map[string]interface{}{"type": "session_end_ack", "end_id": endID}); err != nil {
		t.Fatal(err)
	}
	select {
	case ok := <-complete:
		if !ok {
			t.Fatal("correct ack rejected")
		}
	case <-time.After(time.Second):
		t.Fatal("ack wait stuck")
	}
}

func endIDIsValid(value interface{}) bool {
	s, ok := value.(string)
	return ok && len(s) == 32
}

func TestSessionEndAckTimeout(t *testing.T) {
	left, right := net.Pipe()
	defer left.Close()
	defer right.Close()
	session := NewSession(protocol.NewRATSocket(left), "test-id")
	server := protocol.NewRATSocket(right)
	complete := make(chan bool, 1)
	go func() {
		complete <- session.reportSessionEnd("server_requested_disconnect", "kill_instance", 50*time.Millisecond)
	}()
	msg, err := server.Recv()
	if err != nil || msg["reason"] != "server_requested_disconnect" {
		t.Fatalf("report: %#v %v", msg, err)
	}
	select {
	case ok := <-complete:
		if ok {
			t.Fatal("accepted without ack")
		}
	case <-time.After(time.Second):
		t.Fatal("timeout hung")
	}
}

func TestLifecycleCommandsAreSynchronous(t *testing.T) {
	for _, name := range []string{"kill_instance", "relaunch_instance", "spawn_instance"} {
		spec, ok := LookupCommand(name)
		if !ok || spec.Handler == nil || spec.Runner != nil || spec.CancelPolicy != "none" {
			t.Fatalf("bad lifecycle command %s: %#v", name, spec)
		}
	}
	if _, ok := LookupCommand("kill"); ok {
		t.Fatal("legacy kill command still registered")
	}
}

func TestLifecycleCommandsRejectInvalidArguments(t *testing.T) {
	invalid := []struct {
		name string
		args []string
	}{
		{"kill_instance", []string{"unexpected"}},
		{"relaunch_instance", []string{"--incorrect"}},
		{"spawn_instance", []string{"extra"}},
	}
	for _, item := range invalid {
		spec, ok := LookupCommand(item.name)
		if !ok {
			t.Fatal(item.name)
		}
		status, _ := spec.Handler(nil, item.args)
		if status != 0 {
			t.Fatalf("%s accepted unexpected arguments", item.name)
		}
	}
}

func TestShellCommandManifestDeclaresProcessCancellation(t *testing.T) {
	policies := map[string]string{}
	for _, entry := range CommandManifest() {
		item := entry.(map[string]interface{})
		name := item["name"].(string)
		policies[name] = item["cancel_policy"].(string)
		if _, exists := item["output"]; exists {
			t.Fatal("output mode leaked into command manifest")
		}
	}
	for _, name := range []string{"shell", "shell_stream"} {
		if policies[name] != "process" {
			t.Fatalf("%s policy: %q", name, policies[name])
		}
	}
	if cmd, ok := LookupCommand("shell_stream"); !ok || cmd.Output != "stream" {
		t.Fatal("runtime stream mode missing")
	}
	for _, name := range []string{"kill_instance", "relaunch_instance", "spawn_instance"} {
		if policies[name] != "none" {
			t.Fatalf("%s policy: %q", name, policies[name])
		}
	}
}

func TestSpawnCommandKeepsExecutableAndArgsSeparate(t *testing.T) {
	exe := filepath.Join(string(os.PathSeparator), "some dir", "client")
	cmd := newClientInstanceCommand(exe, []string{"arg with space", "--flag"})
	if cmd.Path != exe || len(cmd.Args) != 3 || cmd.Args[0] != exe || cmd.Args[1] != "arg with space" || cmd.Args[2] != "--flag" || cmd.Dir != filepath.Dir(exe) {
		t.Fatalf("invalid spawn command: %#v", cmd)
	}
	if cmd.SysProcAttr == nil {
		t.Fatal("spawn is not detached")
	}
}

// Run the real exit paths in child test processes so os.Exit cannot terminate
// the test runner. The marker is written only after transfer cancellation.
func TestExplicitExitWaitsForTransfers(t *testing.T) {
	if mode := os.Getenv("RCH_TEST_EXIT_MODE"); mode != "" {
		left, right := net.Pipe()
		session := NewSession(protocol.NewRATSocket(left), "exit-test")
		go func() {
			defer right.Close()
			peer := protocol.NewRATSocket(right)
			for {
				msg, err := peer.Recv()
				if err != nil {
					return
				}
				if msg["type"] == "session_end" {
					if err := peer.Send(map[string]interface{}{"type": "session_end_ack", "end_id": msg["end_id"]}); err != nil {
						return
					}
				}
			}
		}()
		ctx, cancel := context.WithCancel(context.Background())
		if !session.transfers.start("active", cancel) {
			t.Fatal("cannot register transfer")
		}
		go func() {
			defer session.transfers.finish("active")
			<-ctx.Done()
			// Simulate a worker's final cleanup rather than just cancellation.
			time.Sleep(30 * time.Millisecond)
			if err := os.WriteFile(os.Getenv("RCH_TEST_EXIT_MARKER"), []byte("cleaned"), 0600); err != nil {
				panic(err)
			}
		}()
		switch mode {
		case "kill":
			cmdKillInstance(session, nil)
		case "disconnect":
			registration, ok := session.ControlHandler(protocol.ControlSession)
			if !ok {
				t.Fatal("session control unavailable")
			}
			registration.Execute(context.Background(), session, 1, protocol.SessionDisconnect, nil, nil)
		default:
			t.Fatalf("unknown mode %q", mode)
		}
		t.Fatal("exit path returned")
	}
	for _, mode := range []string{"kill", "disconnect"} {
		t.Run(mode, func(t *testing.T) {
			marker := filepath.Join(t.TempDir(), "cleanup")
			ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
			defer cancel()
			cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestExplicitExitWaitsForTransfers$")
			cmd.Env = append(os.Environ(), "RCH_TEST_EXIT_MODE="+mode, "RCH_TEST_EXIT_MARKER="+marker)
			if out, err := cmd.CombinedOutput(); err != nil {
				t.Fatalf("exit process: %v %s", err, out)
			}
			if got, err := os.ReadFile(marker); err != nil || string(got) != "cleaned" {
				t.Fatalf("exited before cleanup: %q %v", got, err)
			}
		})
	}
}
