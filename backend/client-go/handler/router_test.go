package handler

import (
	"net"
	"runtime"
	"strings"
	"testing"
	"time"

	"client-go/executor"
	"client-go/protocol"
)

func pair(t *testing.T) (*executor.Session, *protocol.RATSocket) {
	t.Helper()
	a, b := net.Pipe()
	t.Cleanup(func() { _ = a.Close(); _ = b.Close() })
	return executor.NewSession(protocol.NewRATSocket(a), "test-client"), protocol.NewRATSocket(b)
}

func receive(t *testing.T, peer *protocol.RATSocket) map[string]interface{} {
	t.Helper()
	ch := make(chan map[string]interface{}, 1)
	go func() { v, _ := peer.Recv(); ch <- v }()
	select {
	case v := <-ch:
		if v == nil {
			t.Fatal("socket closed")
		}
		return v
	case <-time.After(3 * time.Second):
		t.Fatal("timed out waiting for protocol result")
	}
	return nil
}

func TestUnsupportedExecutionMessagesReturnFailure(t *testing.T) {
	for _, typ := range []string{"script", "acmd", "job_control"} {
		t.Run(typ, func(t *testing.T) {
			session, peer := pair(t)
			go Handle(session, map[string]interface{}{"type": typ, "id": float64(27), "text": "script body"})
			v := receive(t, peer)
			if v["type"] != "result" || v["status"] != float64(0) || v["eof"] != float64(1) || v["id"] != float64(27) {
				t.Fatalf("bad failed result: %#v", v)
			}
			if !strings.Contains(v["text"].(string), typ) {
				t.Fatalf("unclear error: %#v", v)
			}
		})
	}
}

func TestShellCancelReleasesCommandAndKeepsSocketUsable(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX shell fixture")
	}
	session, peer := pair(t)
	Handle(session, map[string]interface{}{"type": "command", "id": float64(7), "text": "sleep 30"})
	if !session.HasActiveShell() {
		t.Fatal("command not active")
	}
	time.Sleep(150 * time.Millisecond)
	// Cancel must be processed while the command is still running.
	go Handle(session, map[string]interface{}{"type": "cancel", "id": float64(8), "target_id": float64(7)})
	first := receive(t, peer)
	second := receive(t, peer)
	third := receive(t, peer)
	all := []map[string]interface{}{first, second, third}
	accepted, stopped, ended := false, false, false
	for _, v := range all {
		if v["type"] == "cancel_ack" && v["state"] == "accepted" {
			accepted = true
		}
		if v["type"] == "cancel_ack" && v["state"] == "stopped" {
			stopped = true
		}
		if v["type"] == "result" && v["id"] == float64(7) && v["eof"] == float64(1) && v["status"] == float64(0) {
			ended = true
		}
	}
	if !accepted || !stopped || !ended {
		t.Fatalf("cancel incomplete: %#v", all)
	}
	if session.HasActiveShell() {
		t.Fatal("foreground shell was not released")
	}
	go Handle(session, map[string]interface{}{"type": "command", "id": float64(9), "text": "pwd"})
	next := receive(t, peer)
	if next["id"] != float64(9) || next["status"] != float64(1) {
		t.Fatalf("subsequent command failed: %#v", next)
	}
}

func TestNonexistentCancelRejectedWithoutBlocking(t *testing.T) {
	session, peer := pair(t)
	go Handle(session, map[string]interface{}{"type": "cancel", "id": float64(5), "target_id": float64(44)})
	v := receive(t, peer)
	if v["type"] != "cancel_ack" || v["state"] != "rejected" {
		t.Fatalf("bad ack: %#v", v)
	}
}

func TestUnsupportedTransferFinishesWithFailure(t *testing.T) {
	session, peer := pair(t)
	go Handle(session, map[string]interface{}{
		"type": "transfer_start", "transfer_id": "transfer-123", "operation": "server_to_client_file",
	})
	result := receive(t, peer)
	if result["type"] != "transfer_update" || result["transfer_id"] != "transfer-123" ||
		result["state"] != "failed" || result["stage"] != "failed" || result["cancel_supported"] != false {
		t.Fatalf("unexpected transfer failure message: %#v", result)
	}
	if result["error"] == "" {
		t.Fatalf("transfer failure has no reason: %#v", result)
	}
}

func TestHeartbeatEchoesServerTimestampForRTT(t *testing.T) {
	session, peer := pair(t)
	ts := "2026-11-03T12:30:00.987654"
	go Handle(session, map[string]interface{}{"type": "heartbeat", "id": float64(101), "ts": ts})
	response := receive(t, peer)
	if response["type"] != "heartbeat_ack" || response["server_ts"] != ts || response["id"] != float64(101) {
		t.Fatalf("heartbeat lost timestamp required for RTT: %#v", response)
	}
}

func TestExplicitShellCommandsAvailableAndPreserveQuotedArguments(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX shell fixture")
	}
	for _, cmd := range []string{"shell", "shell_stream"} {
		t.Run(cmd, func(t *testing.T) {
			spec, ok := executor.LookupCommand(cmd)
			if !ok || spec.Runner == nil {
				t.Fatalf("%s is not registered as cancellable command", cmd)
			}
			session, peer := pair(t)
			go Handle(session, map[string]interface{}{"type": "command", "id": float64(51), "text": cmd + ` printf '%s\n' 'a b'`})
			var seen, final bool
			for i := 0; i < 5; i++ {
				msg := receive(t, peer)
				if msg["type"] != "result" {
					t.Fatalf("wrong frame: %#v", msg)
				}
				if strings.Contains(msg["text"].(string), "a b") {
					seen = true
				}
				if msg["eof"] == float64(1) {
					final = true
					if msg["status"] != float64(1) {
						t.Fatalf("command failed: %#v", msg)
					}
					break
				}
			}
			if !seen || !final {
				t.Fatalf("output or final frame missing: seen=%v final=%v", seen, final)
			}
		})
	}
}

func TestShellStreamEmitsBeforeCommandFinishes(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX shell fixture")
	}
	session, peer := pair(t)
	Handle(session, map[string]interface{}{"type": "command", "id": float64(62), "text": `shell_stream printf 'first\n'; sleep 1; printf 'second\n'`})
	start := time.Now()
	first := receive(t, peer)
	if first["eof"] != float64(0) || first["text"] != "first" || time.Since(start) >= 800*time.Millisecond {
		t.Fatalf("first output not streamed before completion: %#v elapsed %v", first, time.Since(start))
	}
	second := receive(t, peer)
	final := receive(t, peer)
	if second["eof"] != float64(0) || second["text"] != "second" || final["eof"] != float64(1) || final["status"] != float64(1) {
		t.Fatalf("wrong stream completion: %#v %#v", second, final)
	}
}

func TestExplicitShellStreamCancellation(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX shell fixture")
	}
	session, peer := pair(t)
	Handle(session, map[string]interface{}{"type": "command", "id": float64(70), "text": "shell_stream sleep 30"})
	time.Sleep(150 * time.Millisecond)
	go Handle(session, map[string]interface{}{"type": "cancel", "id": float64(71), "target_id": float64(70)})
	var accepted, stopped, finished bool
	for i := 0; i < 3; i++ {
		msg := receive(t, peer)
		if msg["type"] == "cancel_ack" && msg["state"] == "accepted" {
			accepted = true
		}
		if msg["type"] == "cancel_ack" && msg["state"] == "stopped" {
			stopped = true
		}
		if msg["type"] == "result" && msg["eof"] == float64(1) && msg["status"] == float64(0) {
			finished = true
		}
	}
	if !accepted || !stopped || !finished || session.HasActiveShell() {
		t.Fatalf("cancel incomplete: accepted=%v stopped=%v finished=%v", accepted, stopped, finished)
	}
}

func TestShellStreamStderrAndFailureCompletion(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX shell fixture")
	}
	session, peer := pair(t)
	Handle(session, map[string]interface{}{"type": "command", "id": float64(80), "text": "shell_stream printf 'bad\\n' >&2; exit 7"})
	first, final := receive(t, peer), receive(t, peer)
	if first["text"] != "bad" || first["status"] != float64(0) || first["eof"] != float64(0) ||
		final["eof"] != float64(1) || final["status"] != float64(0) || !strings.Contains(final["text"].(string), "code 7") {
		t.Fatalf("stderr stream or final status wrong: %#v %#v", first, final)
	}
}

func TestShellMissingArgsReturnsTerminalResult(t *testing.T) {
	for _, name := range []string{"shell", "shell_stream"} {
		session, peer := pair(t)
		Handle(session, map[string]interface{}{"type": "command", "id": float64(91), "text": name})
		result := receive(t, peer)
		if result["status"] != float64(0) || result["eof"] != float64(1) || !strings.Contains(result["text"].(string), "Usage") {
			t.Fatalf("unexpected missing args result: %#v", result)
		}
	}
}

func TestExplicitShellReportsExitCode(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX shell fixture")
	}
	session, peer := pair(t)
	Handle(session, map[string]interface{}{"type": "command", "id": float64(93), "text": "shell printf 'oops\\n'; exit 8"})
	result := receive(t, peer)
	if result["status"] != float64(0) || !strings.Contains(result["text"].(string), "oops") || !strings.Contains(result["text"].(string), "code 8") {
		t.Fatalf("shell did not report error details: %#v", result)
	}
}

func TestShellStreamCancelledAfterRealOutputAndSubsequentCommand(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX shell fixture")
	}
	session, peer := pair(t)
	Handle(session, map[string]interface{}{"type": "command", "id": float64(201), "text": "shell_stream echo ready; sleep 30"})
	first := receive(t, peer)
	if first["type"] != "result" || first["eof"] != float64(0) || first["text"] != "ready" {
		t.Fatalf("expected live output before cancel: %#v", first)
	}
	go Handle(session, map[string]interface{}{"type": "cancel", "id": float64(202), "target_id": float64(201)})
	accepted, stopped, final := false, false, false
	for i := 0; i < 3; i++ {
		msg := receive(t, peer)
		if msg["type"] == "cancel_ack" && msg["state"] == "accepted" {
			accepted = true
		}
		if msg["type"] == "cancel_ack" && msg["state"] == "stopped" {
			stopped = true
		}
		if msg["type"] == "result" && msg["eof"] == float64(1) && msg["status"] == float64(0) {
			final = true
		}
	}
	if !accepted || !stopped || !final || session.HasActiveShell() {
		t.Fatalf("cancel incomplete: %v %v %v", accepted, stopped, final)
	}
	go Handle(session, map[string]interface{}{"type": "command", "id": float64(203), "text": "pwd"})
	next := receive(t, peer)
	if next["id"] != float64(203) || next["status"] != float64(1) {
		t.Fatalf("command after cancel failed: %#v", next)
	}
}
