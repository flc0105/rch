package executor

import (
	"client-go/protocol"
	"context"
)

type remoteFileControlHandler func(context.Context, *Session, map[string]interface{}) (int, interface{})

type RemoteFilesManager struct{}

func prepareRemoteQuery(field string) func(*Session, map[string]interface{}) (map[string]interface{}, error) {
	return func(s *Session, p map[string]interface{}) (map[string]interface{}, error) {
		path, err := remotePath(s, payloadText(p[field]))
		if err != nil {
			return nil, err
		}
		result := make(map[string]interface{}, len(p))
		for key, value := range p {
			result[key] = value
		}
		result[field] = path
		return result, nil
	}
}

type remoteFileActionRegistration struct {
	Spec    ControlActionSpec
	Handler remoteFileControlHandler
}

var remoteFileActions = map[protocol.ControlAction]remoteFileActionRegistration{
	protocol.RemoteBrowseDirectory: {Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemoteQuery("path")}, Handler: func(ctx context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return browseDirValue(ctx, s, p)
	}},
	protocol.RemoteCreateDirectory: {Spec: ControlActionSpec{Policy: Foreground}, Handler: func(_ context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return mkdirPathValue(s, payloadText(p["path"]))
	}},
	protocol.RemoteRenamePath: {Spec: ControlActionSpec{Policy: Foreground}, Handler: func(_ context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return renamePathPayload(s, p)
	}},
	protocol.RemoteDeletePaths:      {Spec: ControlActionSpec{Policy: Foreground}, Handler: deletePathsPayload},
	protocol.RemotePastePaths:       {Spec: ControlActionSpec{Policy: Foreground}, Handler: pastePathsPayload},
	protocol.RemoteCreateArchive:    {Spec: ControlActionSpec{Policy: Foreground}, Handler: createRemoteZipPayload},
	protocol.RemotePeekArchive:      {Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemoteQuery("path")}, Handler: peekRemoteZipPayload},
	protocol.RemoteReadArchiveEntry: {Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemoteQuery("path")}, Handler: readRemoteZipEntryPayload},
	protocol.RemoteExtractArchive:   {Spec: ControlActionSpec{Policy: Foreground}, Handler: extractRemoteZipPayload},
	protocol.RemoteInspectUpload: {Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemoteQuery("destination_dir")}, Handler: func(_ context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return inspectRemoteUploadPayload(s, p)
	}},
	protocol.RemoteSaveFile: {Spec: ControlActionSpec{Policy: Foreground}, Handler: func(ctx context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return saveRemoteTextPayload(ctx, s, p)
	}},
}

var remoteFileActionSpecs = func() map[protocol.ControlAction]ControlActionSpec {
	specs := make(map[protocol.ControlAction]ControlActionSpec, len(remoteFileActions))
	for action, registration := range remoteFileActions {
		specs[action] = registration.Spec
	}
	return specs
}()

func (RemoteFilesManager) Execute(ctx context.Context, s *Session, id int, action protocol.ControlAction, payload map[string]interface{}, _ func(int, string)) (int, interface{}) {
	registration, ok := remoteFileActions[action]
	if !ok {
		return 0, "Unsupported remote_files Control action: " + string(action)
	}
	return registration.Handler(ctx, s, payload)
}
