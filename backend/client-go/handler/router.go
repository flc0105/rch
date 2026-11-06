package handler

import (
	"context"
	"fmt"
	"strings"
	"time"

	"client-go/executor"
)

func messageID(msg map[string]interface{}, key string) (int, bool) {
	value, ok := msg[key].(float64)
	if !ok || value <= 0 || value != float64(int(value)) {
		return 0, false
	}
	return int(value), true
}

func sendResult(session *executor.Session, id, status int, text string) {
	_ = session.Sock.Send(map[string]interface{}{
		"type": "result", "id": id, "status": status,
		"text": text, "cwd": session.Cwd, "eof": 1,
	})
}

func Handle(session *executor.Session, msg map[string]interface{}) {
	switch msg["type"] {
	case "heartbeat":
		_ = session.Sock.Send(map[string]interface{}{
			"type": "heartbeat_ack", "id": msg["id"],
			"server_ts": msg["ts"], "client_ts": float64(time.Now().UnixNano()) / 1e9, "cwd": session.Cwd,
		})

	case "transfer_start":
		id, _ := msg["transfer_id"].(string)
		operation, _ := msg["operation"].(string)
		payload, _ := msg["payload"].(map[string]interface{})
		session.StartTransfer(id, operation, payload)

	case "transfer_cancel":
		id, _ := msg["transfer_id"].(string)
		session.CancelTransfer(id)

	case "script", "acmd", "job_control":
		// These are distinct protocol message types, not shell commands.
		// Every received executable request must produce a terminal result.
		if id, ok := messageID(msg, "id"); ok {
			sendResult(session, id, 0, fmt.Sprintf("Unsupported command type on this Client: %s", msg["type"]))
		}

	case "command":
		id, ok := messageID(msg, "id")
		if !ok {
			return
		}
		cmd, ok := msg["text"].(string)
		if !ok {
			sendResult(session, id, 0, "Invalid command text")
			return
		}
		parts := strings.Fields(cmd)
		if len(parts) == 0 {
			sendResult(session, id, 0, "Empty command")
			return
		}
		name := strings.ToLower(parts[0])
		if spec, registered := executor.LookupCommand(name); registered && spec.Runner == nil {
			if session.HasActiveShell() {
				sendResult(session, id, 0, "Client is busy executing a shell command")
				return
			}
			status, result := session.Dispatch(id, cmd)
			sendResult(session, id, status, result)
			return
		}
		ctx, cancel := context.WithCancel(context.Background())
		if !session.BeginShell(id, cancel) {
			cancel()
			sendResult(session, id, 0, "Client is busy executing a shell command")
			return
		}
		go func() {
			defer cancel()
			status, result := session.DispatchContextOutput(ctx, id, cmd, func(streamStatus int, chunk string) {
				_ = session.Sock.Send(map[string]interface{}{
					"type": "result", "id": id, "status": streamStatus,
					"text": chunk, "cwd": session.Cwd, "eof": 0,
				})
			})
			cancelled, cancelID := session.EndShell(id)
			if cancelled {
				status, result = 0, "Command cancelled"
			}
			sendResult(session, id, status, result)
			if cancelled {
				_ = session.Sock.Send(map[string]interface{}{
					"type": "cancel_ack", "id": cancelID,
					"target_id": id, "accepted": true, "state": "stopped",
				})
			}
		}()

	case "cancel":
		id, ok := messageID(msg, "target_id")
		if !ok {
			return
		}
		cancelID, _ := messageID(msg, "id")
		accepted := session.CancelShell(id, cancelID)
		state := "rejected"
		if accepted {
			state = "accepted"
		}
		_ = session.Sock.Send(map[string]interface{}{
			"type": "cancel_ack", "id": cancelID, "target_id": id,
			"accepted": accepted, "state": state,
		})
	}
}
