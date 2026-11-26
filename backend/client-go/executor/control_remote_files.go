package executor

import (
	"client-go/protocol"
	"context"
	"fmt"
)

type remoteFileControlHandler func(context.Context, *Session, map[string]interface{}) (int, interface{})

type RemoteFilesManager struct{}

// Snapshot cwd once for all paths in a request, before the worker is started.
func prepareRemotePaths(defaultFields []string, fields ...string) func(*Session, map[string]interface{}) (map[string]interface{}, error) {
	return func(s *Session, p map[string]interface{}) (map[string]interface{}, error) {
		cwd := s.CurrentDirectory()
		result := make(map[string]interface{}, len(p))
		for key, value := range p {
			result[key] = value
		}
		for _, field := range fields {
			if field == "paths" {
				if paths, ok := p[field].([]interface{}); ok {
					resolved := make([]interface{}, len(paths))
					for i, value := range paths {
						resolved[i] = value
						if raw := payloadText(value); raw != "" {
							path, err := remotePathFromDirectory(cwd, raw)
							if err != nil {
								return nil, err
							}
							resolved[i] = path
						}
					}
					result[field] = resolved
				}
				continue
			}
			raw := payloadText(p[field])
			if raw == "" {
				useCwd := false
				for _, defaultField := range defaultFields {
					if field == defaultField {
						useCwd = true
						break
					}
				}
				if !useCwd {
					continue
				}
			}
			path, err := remotePathFromDirectory(cwd, raw)
			if err != nil {
				return nil, err
			}
			result[field] = path
		}
		return result, nil
	}
}

type remoteFileActionRegistration struct {
	Spec    ControlActionSpec
	Handler remoteFileControlHandler
	Writes  bool
}

var remoteFileActions = map[protocol.ControlAction]remoteFileActionRegistration{
	protocol.RemoteBrowseDirectory: {Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemotePaths([]string{"path"}, "path")}, Handler: func(ctx context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return browseDirValue(ctx, s, p)
	}},
	protocol.RemoteCreateDirectory: {Writes: true, Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemotePaths(nil, "path")}, Handler: func(_ context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return mkdirPathValue(s, payloadText(p["path"]))
	}},
	protocol.RemoteRenamePath: {Writes: true, Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemotePaths(nil, "old_path", "new_path")}, Handler: func(_ context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return renamePathPayload(s, p)
	}},
	protocol.RemoteDeletePaths:      {Writes: true, Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemotePaths(nil, "paths")}, Handler: deletePathsPayload},
	protocol.RemotePastePaths:       {Writes: true, Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemotePaths(nil, "paths", "destination_dir")}, Handler: pastePathsPayload},
	protocol.RemoteCreateArchive:    {Writes: true, Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemotePaths([]string{"destination_dir"}, "paths", "destination_dir")}, Handler: createRemoteZipPayload},
	protocol.RemotePeekArchive:      {Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemotePaths([]string{"path"}, "path")}, Handler: peekRemoteZipPayload},
	protocol.RemoteReadArchiveEntry: {Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemotePaths([]string{"path"}, "path")}, Handler: readRemoteZipEntryPayload},
	protocol.RemoteExtractArchive:   {Writes: true, Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemotePaths([]string{"path", "destination_dir"}, "path", "destination_dir")}, Handler: extractRemoteZipPayload},
	protocol.RemoteInspectUpload: {Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemotePaths([]string{"destination_dir"}, "destination_dir")}, Handler: func(ctx context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return inspectRemoteUploadPayload(ctx, s, p)
	}},
	protocol.RemoteSaveFile: {Writes: true, Spec: ControlActionSpec{Policy: Independent, Prepare: prepareRemotePaths([]string{"path"}, "path")}, Handler: func(ctx context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
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
	if registration.Writes {
		release, err := acquireFilesystemMutation(ctx)
		if err != nil {
			return 0, "Command cancelled"
		}
		defer release()
	}
	status, result := registration.Handler(ctx, s, payload)
	if batch, ok := result.(batchRemoteResult); ok {
		state := "success"
		if batch.Failed > 0 {
			state = "error"
			if batch.Succeeded > 0 {
				state = "partial"
			}
		}
		packet := map[string]interface{}{"event_type": "completed", "status": state, "message": batch.Message}
		if action != protocol.RemoteDeletePaths {
			packet["data"] = map[string]interface{}{"succeeded": batch.Succeeded, "failed": batch.Failed}
		}
		return status, packet
	}
	if status != 1 {
		return status, map[string]interface{}{"event_type": "completed", "status": "error", "message": fmt.Sprint(result)}
	}
	packet := map[string]interface{}{"event_type": "completed", "status": "success", "message": ""}
	switch action {
	case protocol.RemoteCreateDirectory, protocol.RemoteRenamePath, protocol.RemoteSaveFile:
		packet["message"] = fmt.Sprint(result)
	case protocol.RemoteCreateArchive:
		archive, ok := result.(map[string]interface{})
		if !ok {
			return 0, map[string]interface{}{"event_type": "completed", "status": "error", "message": "Invalid archive result"}
		}
		packet["data"] = map[string]interface{}{"archive_name": archive["archive_name"]}
	case protocol.RemotePeekArchive, protocol.RemoteReadArchiveEntry:
		object, ok := result.(map[string]interface{})
		if !ok {
			return 0, map[string]interface{}{"event_type": "completed", "status": "error", "message": "Invalid archive result"}
		}
		fields := []string{"path", "name", "archive_size", "file_count", "dir_count", "entry_count", "uncompressed_size", "tree"}
		if action == protocol.RemoteReadArchiveEntry {
			fields = []string{"type", "content", "message"}
		}
		view := make(map[string]interface{}, len(fields))
		for _, key := range fields {
			if value, exists := object[key]; exists {
				view[key] = value
			}
		}
		packet["data"] = view
	case protocol.RemoteExtractArchive:
		if payloadBool(payload["inspect"]) {
			packet["data"] = result
		} else {
			archive, ok := result.(map[string]interface{})
			if !ok {
				return 0, map[string]interface{}{"event_type": "completed", "status": "error", "message": "Invalid extract result"}
			}
			packet["data"] = map[string]interface{}{"extracted_to": archive["extracted_to"]}
		}
	default:
		packet["data"] = result
	}
	return status, packet
}
