// A preview source owns its label and the operations it supports. Business
// implementations live in the preview save and reload modules.
export const PREVIEW_SOURCE_OPERATIONS = Object.freeze({
  remote_file: {
    label: 'Remote File', requiresCompleteContent: true,
    save: (vm, content) => vm.saveToRemoteFile(content),
    reload: vm => vm.fetchLatestRemoteFileTextPayload(),
  },
  artifact: {
    label: 'Artifact', requiresCompleteContent: true,
    save: (vm, content) => vm.saveToArtifact(content),
    reload: vm => vm.fetchLatestArtifactTextPayload(),
  },
  new_shared_file: {
    label: 'Artifact',
    save: (vm, content) => vm.saveToNewSharedFile(content),
    reload: () => { throw new Error('This file has not been created yet') },
  },
  job_attachment: { label: 'Background Job' },
  background_job: {
    label: 'Background Job',
    save: (vm, content) => vm.saveToBackgroundJob(content),
    reload: vm => vm.fetchLatestBackgroundJobTextPayload(),
  },
  server_script: {
    label: 'Server Script',
    save: (vm, content) => vm.saveToServerScript(content),
    reload: vm => vm.fetchLatestServerScriptTextPayload(),
  },
  external_tool_meta: {
    label: 'External Tool Meta',
    save: (vm, content) => vm.saveToExternalToolMeta(content),
    reload: vm => vm.fetchLatestExternalToolMetaTextPayload(),
  },
})
