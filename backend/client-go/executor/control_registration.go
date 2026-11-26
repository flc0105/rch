package executor

import (
	"client-go/protocol"
	"context"
)

func newControlHandlers() map[protocol.ControlDomain]ControlDomainRegistration {
	return map[protocol.ControlDomain]ControlDomainRegistration{
		protocol.ControlSession: {Execute: func(_ context.Context, s *Session, _ int, _ protocol.ControlAction, _ map[string]interface{}, _ func(int, string)) (int, interface{}) {
			s.exitProcess()
			return 1, ""
		}, NonCancellable: true, Actions: map[protocol.ControlAction]ControlActionSpec{
			protocol.SessionDisconnect: {Policy: Independent},
		}},
		protocol.ControlRemoteFiles: {Execute: (RemoteFilesManager{}).Execute, CancelledMessage: "Command cancelled", Actions: remoteFileActionSpecs},
		protocol.ControlScript: {Execute: (ScriptManager{}).Execute, CancelledMessage: "Script cancelled", Actions: map[protocol.ControlAction]ControlActionSpec{
			protocol.ScriptRun: {Policy: Foreground},
		}},
		protocol.ControlConfiguration: {Execute: (ConfigurationManager{}).Execute, NonCancellable: true, Actions: map[protocol.ControlAction]ControlActionSpec{
			protocol.ConfigurationGet:   {Policy: Independent},
			protocol.ConfigurationSet:   {Policy: Foreground},
			protocol.ConfigurationReset: {Policy: Foreground},
		}},
	}
}
