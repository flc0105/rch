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
	transfers            transferTracker
	controlHandlers      map[protocol.ControlDomain]ControlDomainRegistration
	shellMu              sync.Mutex
	shellCommandID       int
	shellCancel          context.CancelFunc
	shellCancelID        int
	shellCancelRequested bool
	cwdMu                sync.RWMutex
	independent          map[int]*independentExecution
	executionClosed      bool
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

	session := &Session{
		Sock:        sock,
		ClientID:    strings.TrimSpace(clientID),
		HostName:    host,
		Cwd:         wd,
		independent: make(map[int]*independentExecution),
	}
	session.controlHandlers = newControlHandlers()
	return session
}

// Shell commands are the only cancellable execution mode in the minimal Go Client.
func (s *Session) BeginShell(id int, cancel context.CancelFunc) bool {
	s.shellMu.Lock()
	defer s.shellMu.Unlock()
	if s.executionClosed || s.shellCommandID != 0 || s.independent[id] != nil {
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
	if request := s.independent[id]; request != nil {
		if request.cancel == nil {
			return false
		}
		if !request.cancelled {
			request.cancelled = true
			request.cancelID = cancelID
			request.cancel()
		}
		return true
	}
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
	if request := s.independent[id]; request != nil {
		delete(s.independent, id)
		return request.cancelled, request.cancelID
	}
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

type independentExecution struct {
	cancel    context.CancelFunc
	cancelled bool
	cancelID  int
}

const independentCapacity = 4

func (s *Session) BeginExecution(id int, cancel context.CancelFunc, policy ExecutionPolicy) bool {
	if policy == Foreground {
		return s.BeginShell(id, cancel)
	}
	s.shellMu.Lock()
	defer s.shellMu.Unlock()
	if s.executionClosed || len(s.independent) >= independentCapacity || s.shellCommandID == id || s.independent[id] != nil {
		return false
	}
	s.independent[id] = &independentExecution{cancel: cancel}
	return true
}

func (s *Session) CloseExecutions() {
	s.shellMu.Lock()
	defer s.shellMu.Unlock()
	s.executionClosed = true
	for _, request := range s.independent {
		if request.cancel != nil {
			request.cancel()
		}
	}
	if s.shellCancel != nil {
		s.shellCancel()
	}
}

func (s *Session) CurrentDirectory() string {
	s.cwdMu.RLock()
	defer s.cwdMu.RUnlock()
	return s.Cwd
}

func (s *Session) setCurrentDirectory(path string) {
	s.cwdMu.Lock()
	defer s.cwdMu.Unlock()
	s.Cwd = path
}
