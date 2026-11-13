package executor

import (
	"context"
	"encoding/json"
)

type remoteFileControlHandler func(context.Context, *Session, map[string]interface{}) (int, string)

type remoteFileControlAction struct {
	run        remoteFileControlHandler
	structured bool
}

// The same filesystem implementations serve text commands and typed Control.
// Each action maps directly to an operation; Control does not synthesize CLI text.
var remoteFileControlActions = map[string]remoteFileControlAction{
	"browse_directory": {func(ctx context.Context, s *Session, p map[string]interface{}) (int, string) {
		return browseDirValue(ctx, s, p)
	}, true},
	"create_directory": {func(_ context.Context, s *Session, p map[string]interface{}) (int, string) {
		return mkdirPathValue(s, payloadText(p["path"]))
	}, false},
	"rename_path": {func(_ context.Context, s *Session, p map[string]interface{}) (int, string) {
		return renamePathPayload(s, p)
	}, false},
	"delete_paths":       {deletePathsPayload, true},
	"paste_paths":        {pastePathsPayload, true},
	"create_archive":     {createRemoteZipPayload, true},
	"peek_archive":       {peekRemoteZipPayload, true},
	"read_archive_entry": {readRemoteZipEntryPayload, true},
	"extract_archive":    {extractRemoteZipPayload, true},
	"inspect_upload": {func(_ context.Context, s *Session, p map[string]interface{}) (int, string) {
		return inspectRemoteUploadPayload(s, p)
	}, true},
	"save_file": {saveRemoteTextPayload, false},
}

func RemoteFilesControl(ctx context.Context, s *Session, commandID int, action string, payload map[string]interface{}) (int, interface{}) {
	spec, ok := remoteFileControlActions[action]
	if !ok {
		return 0, "Unsupported remote_files Control action: " + action
	}
	s.CurrentCommandID = commandID
	defer func() { s.CurrentCommandID = 0 }()
	status, result := spec.run(ctx, s, payload)
	if status == 1 && spec.structured {
		var data map[string]interface{}
		if err := json.Unmarshal([]byte(result), &data); err != nil || data == nil {
			return 0, "Invalid remote file result"
		}
		return status, data
	}
	return status, result
}
