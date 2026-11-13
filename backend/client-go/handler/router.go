package handler

import (
	"context"
	"fmt"
	"strings"
	"time"

	"client-go/executor"
	"client-go/protocol"
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
		"text": text, "cwd": session.CurrentDirectory(), "eof": 1,
	})
}

func Handle(session *executor.Session, msg map[string]interface{}) {
	switch msg["type"] {
	case "heartbeat":
		_ = session.Sock.Send(map[string]interface{}{
			"type": "heartbeat_ack", "id": msg["id"],
			"server_ts": msg["ts"], "client_ts": float64(time.Now().UnixNano()) / 1e9, "cwd": session.CurrentDirectory(),
		})

	case "transfer_start":
		id, _ := msg["transfer_id"].(string)
		operation, _ := msg["operation"].(string)
		payload, _ := msg["payload"].(map[string]interface{})
		session.StartTransfer(id, operation, payload)

	case "transfer_cancel":
		id, _ := msg["transfer_id"].(string)
		session.CancelTransfer(id)

	case "acmd":
		// These are distinct protocol message types, not shell commands.
		// Every received executable request must produce a terminal result.
		if id, ok := messageID(msg, "id"); ok {
			sendResult(session, id, 0, fmt.Sprintf("Unsupported command type on this Client: %s", msg["type"]))
		}

	case "control":
		id, ok := messageID(msg, "id")
		if !ok {
			return
		}
		domain, _ := msg["domain"].(string)
		action, _ := msg["action"].(string)
		payload, valid := msg["payload"].(map[string]interface{})
		if !valid || action == "" || domain == "" {
			sendResult(session, id, 0, "Invalid Control request")
			return
		}
		control, supported := session.ControlHandler(protocol.ControlDomain(domain))
		if !supported {
			sendResult(session, id, 0, "Unsupported Control domain on this Client: "+domain)
			return
		}
		controlAction := protocol.ControlAction(action)
		spec, registered := control.Action(controlAction)
		if !registered {
			sendResult(session, id, 0, "Unsupported Control action: "+domain+"/"+action)
			return
		}
		if spec.Prepare != nil {
			var err error
			payload, err = spec.Prepare(session, payload)
			if err != nil {
				sendResult(session, id, 0, err.Error())
				return
			}
		}
		ctx, cancel := context.WithCancel(context.Background())
		if spec.Policy == executor.Independent {
			cancel()
			timeout := 3600.0
			if extra, ok := msg["extra"].(map[string]interface{}); ok {
				if value, ok := extra["timeout"].(float64); ok && value > 0 && value <= 86400 {
					timeout = value
				}
			}
			ctx, cancel = context.WithTimeout(context.Background(), time.Duration(timeout*float64(time.Second)))
		}
		var cancelHandler context.CancelFunc = cancel
		if control.NonCancellable {
			cancelHandler = nil
		}
		if !session.BeginExecution(id, cancelHandler, spec.Policy) {
			cancel()
			if spec.Policy == executor.Independent {
				sendResult(session, id, 0, "Independent Control capacity exhausted")
			} else {
				sendResult(session, id, 0, "Client is busy executing a foreground command")
			}
			return
		}
		go func() {
			defer cancel()
			status, result := control.Execute(ctx, session, id, controlAction, payload, func(streamStatus int, chunk string) {
				_ = session.Sock.Send(map[string]interface{}{"type": "result", "id": id, "status": streamStatus, "text": chunk, "cwd": session.CurrentDirectory(), "eof": 0})
			})
			cancelled, cancelID := session.EndShell(id)
			if spec.Policy == executor.Independent && ctx.Err() == context.DeadlineExceeded {
				status, result = 0, map[string]interface{}{"event_type": "error", "failure_reason": "timed_out", "text": "Control request timed out"}
			}
			if cancelled {
				// Preserve explicit structured interruption and partial output,
				// otherwise keep the existing generic cancellation result.
				data, structured := result.(map[string]interface{})
				if !structured || (data["failure_reason"] != "cancelled" && data["failure_reason"] != "timed_out") {
					status, result = 0, control.CancelledMessage
				}
			}
			response := map[string]interface{}{"type": "result", "id": id, "status": status, "cwd": session.CurrentDirectory(), "eof": 1}
			if text, ok := result.(string); ok {
				response["text"] = text
			} else {
				response["data"] = result
			}
			_ = session.Sock.Send(response)
			if cancelled {
				_ = session.Sock.Send(map[string]interface{}{
					"type": "cancel_ack", "id": cancelID, "target_id": id, "accepted": true, "state": "stopped",
				})
			}
		}()

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
					"text": chunk, "cwd": session.CurrentDirectory(), "eof": 0,
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
