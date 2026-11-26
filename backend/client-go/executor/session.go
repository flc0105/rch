package executor

import (
	"client-go/config"
	"context"
	"fmt"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"client-go/protocol"
)

type Session struct {
	Sock                 *protocol.RATSocket
	ClientID             string
	HostName             string
	Cwd                  string
	CurrentCommandID     int
	transfers            transferTracker
	closeOnce            sync.Once
	controlHandlers      map[protocol.ControlDomain]ControlDomainRegistration
	shellMu              sync.Mutex
	shellCommandID       int
	shellCancel          context.CancelFunc
	shellCancelID        int
	shellCancelRequested bool
	cwdMu                sync.RWMutex
	independent          map[int]*independentExecution
	executionClosed      bool
	webMu                sync.RWMutex
	webBaseURL           string
	webEndpointRequired  bool
	transferMu           sync.RWMutex
	sessionToken         string
	fileDataOpener       func(context.Context, string, string, func()) (net.Conn, error)
	registrationMu       sync.Mutex
	pendingRegistrations map[string]chan map[string]interface{}
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

// Close releases managed work before the session is discarded. Closing the
// socket first unblocks workers sending progress or waiting for registration.
func (s *Session) Close() {
	s.closeOnce.Do(func() {
		_ = s.Sock.Close()
		s.CloseTransfers()
		s.CloseExecutions()
	})
}

func (s *Session) exitProcess() {
	s.Close()
	os.Exit(0)
}

// RequireSessionWebEndpoint makes Bind wait for the Server's session_config.
// Reverse keeps its build-time Web endpoint.
func (s *Session) RequireSessionWebEndpoint() {
	s.webMu.Lock()
	defer s.webMu.Unlock()
	s.webEndpointRequired = true
	s.webBaseURL = ""
}

func (s *Session) SetServerWebBaseURL(raw string) error {
	endpoint, err := url.Parse(raw)
	if err != nil || endpoint == nil || (endpoint.Scheme != "http" && endpoint.Scheme != "https") ||
		endpoint.Hostname() == "" || endpoint.User != nil || endpoint.Path != "" ||
		endpoint.RawQuery != "" || endpoint.Fragment != "" || strings.TrimSpace(raw) != raw {
		return fmt.Errorf("invalid Server Web URL")
	}
	if port := endpoint.Port(); port != "" {
		value, err := strconv.Atoi(port)
		if err != nil || value < 1 || value > 65535 {
			return fmt.Errorf("invalid Server Web URL port")
		}
	}
	s.webMu.Lock()
	defer s.webMu.Unlock()
	s.webBaseURL = strings.TrimRight(raw, "/")
	s.webEndpointRequired = true
	return nil
}

func (s *Session) ServerWebBaseURL() string {
	s.webMu.RLock()
	defer s.webMu.RUnlock()
	if s.webEndpointRequired {
		return s.webBaseURL
	}
	return config.UPLOAD_BASE_URL
}

// Transfer registrations are responses on the existing control connection.
func (s *Session) AcceptTransferRegistration(packet map[string]interface{}) {
	id, _ := packet["transfer_id"].(string)
	s.registrationMu.Lock()
	pending := s.pendingRegistrations[id]
	if pending != nil {
		select {
		case pending <- packet:
		default:
		}
	}
	s.registrationMu.Unlock()
}

func (s *Session) registerTransfer(ctx context.Context, id string, payload map[string]interface{}) error {
	reply := make(chan map[string]interface{}, 1)
	s.registrationMu.Lock()
	if s.pendingRegistrations == nil {
		s.pendingRegistrations = make(map[string]chan map[string]interface{})
	}
	s.pendingRegistrations[id] = reply
	s.registrationMu.Unlock()
	defer func() { s.registrationMu.Lock(); delete(s.pendingRegistrations, id); s.registrationMu.Unlock() }()
	payload["type"] = "transfer_register"
	payload["transfer_id"] = id
	if err := s.Sock.Send(payload); err != nil {
		return err
	}
	timer := time.NewTimer(15 * time.Second)
	defer timer.Stop()
	select {
	case result := <-reply:
		if result["accepted"] == true {
			return nil
		}
		return fmt.Errorf("file transfer registration rejected: %v", result["error"])
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return fmt.Errorf("timed out registering file transfer")
	}
}

// File data connections are authorized by the token issued for this active session.
func (s *Session) SetSessionToken(token string) {
	s.transferMu.Lock()
	defer s.transferMu.Unlock()
	s.sessionToken = strings.TrimSpace(token)
}
func (s *Session) SetFileDataOpener(opener func(context.Context, string, string, func()) (net.Conn, error)) {
	s.transferMu.Lock()
	defer s.transferMu.Unlock()
	s.fileDataOpener = opener
}
func (s *Session) openFileData(ctx context.Context, id string) (net.Conn, error) {
	s.transferMu.RLock()
	token, open := s.sessionToken, s.fileDataOpener
	s.transferMu.RUnlock()
	if token == "" {
		return nil, fmt.Errorf("Client Session Token is unavailable")
	}
	if open == nil {
		return nil, fmt.Errorf("file data socket is unavailable")
	}
	conn, err := open(ctx, id, token, func() { s.transferUpdate(id, map[string]interface{}{"data_ready": true}) })
	if err != nil {
		return nil, err
	}
	stop := cancelFileSocket(ctx, conn)
	defer stop()
	ack, err := receiveFileControl(conn)
	if err == nil && ack["ok"] != true {
		err = fmt.Errorf("file data connection rejected: %v", ack["error"])
	}
	if err != nil {
		conn.Close()
		return nil, err
	}
	if err = conn.SetDeadline(time.Time{}); err != nil {
		conn.Close()
		return nil, err
	}
	return conn, nil
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
