package protocol

// ControlDomain and ControlAction are identifiers on the shared Control wire contract.
// Domain/action validation is performed by the Client registration, not the transport.
type ControlDomain string
type ControlAction string

const (
	ControlJob           ControlDomain = "job"
	ControlRemoteFiles   ControlDomain = "remote_files"
	ControlScript        ControlDomain = "script"
	ControlClipboard     ControlDomain = "clipboard"
	ControlConfiguration ControlDomain = "configuration"
	ControlProcess       ControlDomain = "process"
	ControlWatchdog      ControlDomain = "watchdog"
	ControlSession       ControlDomain = "session"
)

const (
	JobStart                   ControlAction = "start"
	JobStop                    ControlAction = "stop"
	JobStopAll                 ControlAction = "stop_all"
	JobPS                      ControlAction = "ps"
	JobStatus                  ControlAction = "status"
	RemoteBrowseDirectory      ControlAction = "browse_directory"
	RemoteCreateDirectory      ControlAction = "create_directory"
	RemoteRenamePath           ControlAction = "rename_path"
	RemoteDeletePaths          ControlAction = "delete_paths"
	RemotePastePaths           ControlAction = "paste_paths"
	RemoteCreateArchive        ControlAction = "create_archive"
	RemotePeekArchive          ControlAction = "peek_archive"
	RemoteReadArchiveEntry     ControlAction = "read_archive_entry"
	RemoteExtractArchive       ControlAction = "extract_archive"
	RemoteInspectUpload        ControlAction = "inspect_upload"
	RemoteSaveFile             ControlAction = "save_file"
	ScriptRun                  ControlAction = "run"
	ClipboardGet               ControlAction = "get"
	ClipboardSet               ControlAction = "set"
	ConfigurationGet           ControlAction = "get"
	ConfigurationSet           ControlAction = "set"
	ConfigurationReset         ControlAction = "reset"
	ProcessKill                ControlAction = "kill"
	WatchdogStatus             ControlAction = "status"
	SessionDisconnect          ControlAction = "disconnect"
	SessionGetRevisionFiles    ControlAction = "get_revision_files"
	SessionGetVariableManifest ControlAction = "get_variable_manifest"
)
