package executor

import (
	"client-go/protocol"
	"context"
)

type ControlHandler func(context.Context, *Session, int, protocol.ControlAction, map[string]interface{}, func(int, string)) (int, interface{})

type ExecutionPolicy string

const (
	Foreground  ExecutionPolicy = "foreground"
	Independent ExecutionPolicy = "independent"
)

type ControlActionSpec struct {
	Policy  ExecutionPolicy
	Prepare func(*Session, map[string]interface{}) (map[string]interface{}, error)
}

type ControlDomainRegistration struct {
	Execute          ControlHandler
	CancelledMessage string
	NonCancellable   bool
	Actions          map[protocol.ControlAction]ControlActionSpec
}

func (d ControlDomainRegistration) Action(action protocol.ControlAction) (ControlActionSpec, bool) {
	spec, ok := d.Actions[action]
	return spec, ok
}

func (s *Session) ControlHandler(domain protocol.ControlDomain) (ControlDomainRegistration, bool) {
	handler, ok := s.controlHandlers[domain]
	return handler, ok
}
