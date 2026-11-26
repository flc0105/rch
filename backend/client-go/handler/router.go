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

// sendResultEvent is the single executable-result wire encoder. Existing
// execution handlers still return (status, result); no EOF crosses the socket.
func sendResultEvent(session *executor.Session, id, status int, result interface{}, phase string) {
	packet := map[string]interface{}{
		"type": "result", "id": id, "event_type": phase,
		"cwd": session.CurrentDirectory(),
	}
	if value, ok := result.(map[string]interface{}); ok {
		if _, typed := value["event_type"]; typed {
			for _, field := range []string{"message", "data", "references", "action"} {
				if item, present := value[field]; present {
					packet[field] = item
				}
			}
			if phase == "progress" {
				if level, ok := value["level"].(string); ok {
					switch level {
					case "info", "success", "warning", "error":
						packet["level"] = level
					}
				}
			}
			if _, present := packet["message"]; !present {
				if text, ok := value["text"].(string); ok {
					packet["message"] = text
				}
			}
			if phase == "completed" {
				if statusName, ok := value["status"].(string); ok {
					packet["status"] = statusName
				}
				if reason, ok := value["failure_reason"].(string); ok &&
					(reason == "cancelled" || reason == "timed_out" || reason == "interrupted") {
					packet["status"] = reason
				} else if value["event_type"] == "cancelled" {
					packet["status"] = "cancelled"
				}
			}
		} else {
			packet["data"] = value
		}
	} else if text, ok := result.(string); ok {
		packet["message"] = text
	} else if result != nil {
		packet["data"] = result
	}
	if phase == "completed" {
		if _, ok := packet["status"]; !ok {
			if status == 1 {
				packet["status"] = "success"
			} else {
				packet["status"] = "error"
			}
		}
		if status != 1 && packet["status"] == "success" {
			packet["status"] = "error"
		}
	}
	_ = session.Sock.Send(packet)
}

func sendResult(session *executor.Session, id, status int, text string) {
	sendResultEvent(session, id, status, text, "completed")
}

func Handle(session *executor.Session, msg map[string]interface{}) {
	switch msg["type"] {
	case "completion":
		id, ok := messageID(msg, "id")
		if !ok {
			return
		}
		result, err := executor.CompleteCommandCompletion(session, msg)
		if err != nil {
			sendResultEvent(session, id, 0, map[string]interface{}{
				"event_type": "completed", "status": "error", "message": err.Error(),
			}, "completed")
			return
		}
		sendResultEvent(session, id, 1, map[string]interface{}{
			"event_type": "completed", "status": "success", "message": "", "data": result,
		}, "completed")

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

	case "transfer_register":
		session.AcceptTransferRegistration(msg)

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
				sendResult(session, id, 0, "Another operation is running on this client. Please try again when it finishes.")
			}
			return
		}
		go func() {
			defer cancel()
			status, result := control.Execute(ctx, session, id, controlAction, payload, func(streamStatus int, chunk string) {
				sendResultEvent(session, id, streamStatus, chunk, "chunk")
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
					status, result = 0, map[string]interface{}{"event_type": "cancelled", "failure_reason": "cancelled", "text": control.CancelledMessage}
				}
			}
			sendResultEvent(session, id, status, result, "completed")
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
				sendResult(session, id, 0, "Another operation is running on this client. Please try again when it finishes.")
				return
			}
			status, result := session.Dispatch(id, cmd)
			sendResult(session, id, status, result)
			return
		}
		ctx, cancel := context.WithCancel(context.Background())
		if !session.BeginShell(id, cancel) {
			cancel()
			sendResult(session, id, 0, "Another operation is running on this client. Please try again when it finishes.")
			return
		}
		go func() {
			defer cancel()
			status, result := session.DispatchContextOutput(ctx, id, cmd, func(streamStatus int, chunk string) {
				sendResultEvent(session, id, streamStatus, chunk, "chunk")
			})
			cancelled, cancelID := session.EndShell(id)
			if cancelled {
				status, result = 0, "Command cancelled"
				sendResultEvent(session, id, status, map[string]interface{}{"event_type": "cancelled", "message": result, "status": "cancelled"}, "completed")
			} else {
				sendResult(session, id, status, result)
			}
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
