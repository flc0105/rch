package executor

import (
	"client-go/protocol"
	"testing"
)

func TestControlRegistrationCoversEverySupportedAction(t *testing.T) {
	registered := newControlHandlers()
	if len(registered) != 4 {
		t.Fatalf("unexpected supported domains: %v", registered)
	}
	if spec, ok := registered[protocol.ControlSession].Action(protocol.SessionDisconnect); !ok || spec.Policy != Independent {
		t.Fatal("Session disconnect must use an independent control action")
	}
	remote := registered[protocol.ControlRemoteFiles]
	if len(remote.Actions) != 11 || len(remote.Actions) != len(remoteFileActions) {
		t.Fatalf("incomplete Remote Files action registration: %v", remote.Actions)
	}
	for action, spec := range remote.Actions {
		if spec.Policy != Independent || spec.Prepare == nil {
			t.Fatalf("unexpected policy or preparer for %s", action)
		}
	}
	for _, action := range []protocol.ControlAction{protocol.ConfigurationGet, protocol.ConfigurationSet, protocol.ConfigurationReset} {
		expected := Foreground
		if action == protocol.ConfigurationGet {
			expected = Independent
		}
		if spec, ok := registered[protocol.ControlConfiguration].Action(action); !ok || spec.Policy != expected {
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
