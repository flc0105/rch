package executor

import "context"

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

var remoteFileActionPolicies = map[string]ControlActionSpec{
	"browse_directory":   {Policy: Independent, Prepare: prepareRemoteQuery("path")},
	"peek_archive":       {Policy: Independent, Prepare: prepareRemoteQuery("path")},
	"read_archive_entry": {Policy: Independent, Prepare: prepareRemoteQuery("path")},
	"inspect_upload":     {Policy: Independent, Prepare: prepareRemoteQuery("destination_dir")},
}

var remoteFileControlActions = map[string]remoteFileControlHandler{
	"browse_directory": func(ctx context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return browseDirValue(ctx, s, p)
	},
	"create_directory": func(_ context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return mkdirPathValue(s, payloadText(p["path"]))
	},
	"rename_path": func(_ context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return renamePathPayload(s, p)
	},
	"delete_paths":       deletePathsPayload,
	"paste_paths":        pastePathsPayload,
	"create_archive":     createRemoteZipPayload,
	"peek_archive":       peekRemoteZipPayload,
	"read_archive_entry": readRemoteZipEntryPayload,
	"extract_archive":    extractRemoteZipPayload,
	"inspect_upload": func(_ context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return inspectRemoteUploadPayload(s, p)
	},
	"save_file": func(ctx context.Context, s *Session, p map[string]interface{}) (int, interface{}) {
		return saveRemoteTextPayload(ctx, s, p)
	},
}

func (RemoteFilesManager) Execute(ctx context.Context, s *Session, id int, action string, payload map[string]interface{}, _ func(int, string)) (int, interface{}) {
	handler, ok := remoteFileControlActions[action]
	if !ok {
		return 0, "Unsupported remote_files Control action: " + action
	}
	return handler(ctx, s, payload)
}
