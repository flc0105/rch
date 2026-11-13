package executor

import "client-go/protocol"

func newControlHandlers() map[protocol.ControlDomain]ControlDomainRegistration {
	return map[protocol.ControlDomain]ControlDomainRegistration{
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
