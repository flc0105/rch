package executor

import (
	"crypto/rand"
	"encoding/hex"
	"time"
)

const sessionEndAckTimeout = 2 * time.Second

// ReportSessionEnd waits for the Server to record the shutdown reason before exiting.
// This is called synchronously from a terminating command on the Client's receive loop.
func (s *Session) ReportSessionEnd(reason, command string) bool {
	return s.reportSessionEnd(reason, command, sessionEndAckTimeout)
}

func (s *Session) reportSessionEnd(reason, command string, timeout time.Duration) bool {
	var id [16]byte
	if _, err := rand.Read(id[:]); err != nil {
		return false
	}
	endID := hex.EncodeToString(id[:])
	if err := s.Sock.Send(map[string]interface{}{
		"type": "session_end", "reason": reason, "end_id": endID,
		"detail": map[string]interface{}{"command": command},
	}); err != nil {
		return false
	}
	if err := s.Sock.SetReadDeadline(time.Now().Add(timeout)); err != nil {
		return false
	}
	defer s.Sock.SetReadDeadline(time.Time{})
	for {
		msg, err := s.Sock.Recv()
		if err != nil {
			return false
		}
		if msg["type"] == "session_end_ack" && msg["end_id"] == endID {
			return true
		}
	}
}
