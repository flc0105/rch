package executor

import (
	"client-go/protocol"
	"testing"
)

func TestControlRegistrationCoversEverySupportedAction(t *testing.T) {
	registered := newControlHandlers()
	if len(registered) != 3 {
		t.Fatalf("unexpected supported domains: %v", registered)
	}
	remote := registered[protocol.ControlRemoteFiles]
	if len(remote.Actions) != 11 || len(remote.Actions) != len(remoteFileActions) {
		t.Fatalf("incomplete Remote Files action registration: %v", remote.Actions)
	}
	reads := map[protocol.ControlAction]bool{
		protocol.RemoteBrowseDirectory: true, protocol.RemotePeekArchive: true,
		protocol.RemoteReadArchiveEntry: true, protocol.RemoteInspectUpload: true,
	}
	for action, spec := range remote.Actions {
		if (spec.Policy == Independent) != reads[action] || (spec.Prepare != nil) != reads[action] {
			t.Fatalf("unexpected policy or preparer for %s", action)
		}
	}
	for _, action := range []protocol.ControlAction{protocol.ConfigurationGet, protocol.ConfigurationSet, protocol.ConfigurationReset} {
		if spec, ok := registered[protocol.ControlConfiguration].Action(action); !ok || spec.Policy != Foreground {
			t.Fatalf("missing Configuration action %s", action)
		}
	}
	if spec, ok := registered[protocol.ControlScript].Action(protocol.ScriptRun); !ok || spec.Policy != Foreground {
		t.Fatal("Script run must be foreground")
	}
	if _, ok := remote.Action(protocol.ScriptRun); ok {
		t.Fatal("unknown Remote Files action was accepted")
	}
}
