"""Shared Files upload planning and commit. Artifact IDs remain independent of display names."""
from dataclasses import dataclass

from core.artifact_contract import ArtifactType
from server.application.transfers.upload_plan import UploadPlan

SHARED = ArtifactType.SHARED.value


def _folder_key(name):
    # SQLite NOCASE folds ASCII only, unlike str.casefold(). Match the Catalog.
    return name.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))


@dataclass
class SharedUploadIncomplete(ValueError):
    files_uploaded: int
    folders_created: int
    total_files: int
    error: str

    def __str__(self):
        return (f'Shared upload stopped after {self.files_uploaded}/{self.total_files} file(s), '
                f'{self.folders_created} folder(s) created: {self.error}')


class SharedUploadService:
    def __init__(self, artifacts):
        self.artifacts = artifacts

    def _prepare(self, paths, directories, parent_folder_id):
        plan = UploadPlan.build(paths, directories, max_folders=2000)
        for path in (*plan.files, *plan.directories):
            # Catalog trims folder names. Refuse ambiguous input before making any changes.
            if any(part != part.strip() or len(part) > 120 for part in path.split('/')):
                raise ValueError(f'Invalid Shared upload path: {path}')
        aliases = [_folder_key(path) for path in plan.directories]
        if len(aliases) != len(set(aliases)) or set(aliases).intersection(_folder_key(path) for path in plan.files):
            raise ValueError('Invalid or ambiguous Shared folder paths')
        folders = self.artifacts.list_folders(SHARED)
        if parent_folder_id and not any(row['folder_id'] == parent_folder_id for row in folders):
            raise ValueError('Folder does not belong to Shared Files')
        known = {(row.get('parent_id') or '', _folder_key(row['name'])): row['folder_id'] for row in folders}
        by_path = {}
        for path in plan.directories:
            parent, _, name = path.rpartition('/')
            parent_id = by_path[parent] if parent else parent_folder_id
            by_path[path] = known.get((parent_id or '', _folder_key(name))) if parent_id is not None else None
        names = self.artifacts.shared_file_names()
        conflicts = []
        for index, path in enumerate(plan.files):
            parent, _, name = path.rpartition('/')
            folder = by_path[parent] if parent else parent_folder_id
            if folder is not None and (folder or '', name) in names:
                conflicts.append({'index': index, 'source': path, 'target': path,
                                  'source_kind': 'file', 'target_kind': 'file',
                                  'allowed_actions': ['stop', 'skip', 'keep_both']})
        return plan, by_path, conflicts

    def inspect(self, paths, directories, parent_folder_id=''):
        plan, by_path, conflicts = self._prepare(paths, directories, parent_folder_id)
        return {'conflicts': conflicts, 'folder_count': len(plan.directories),
                'folders_reused': sum(value is not None for value in by_path.values())}

    def upload(self, *, files, paths, directories, parent_folder_id='', conflict_policies):
        plan, by_path, conflicts = self._prepare(paths, directories, parent_folder_id)
        if len(files) != len(plan.files) or any(upload.filename != path.rsplit('/', 1)[-1] for upload, path in zip(files, plan.files)):
            raise ValueError('Shared upload filename mismatch')
        if (not isinstance(conflict_policies, list) or len(conflict_policies) != len(files)
                or any(policy not in ('stop', 'skip', 'keep_both') for policy in conflict_policies)):
            raise ValueError('Invalid Shared upload conflict policies')
        if any(conflict_policies[item['index']] == 'stop' for item in conflicts):
            raise ValueError('Shared upload destination has changed or contains an unresolved file conflict')
        created = saved = skipped = 0
        try:
            for path in plan.directories:
                if by_path[path] is not None:
                    continue
                parent, _, name = path.rpartition('/')
                parent_id = by_path[parent] if parent else parent_folder_id
                by_path[path] = self.artifacts.create_folder(SHARED, name, parent_id or '')['folder_id']
                created += 1
            for upload, path, policy in zip(files, plan.files, conflict_policies):
                if policy == 'skip':
                    skipped += 1
                    continue
                parent, _, name = path.rpartition('/')
                folder_id = by_path[parent] if parent else parent_folder_id
                self.artifacts.save_shared_upload_file(upload, folder_id or '', policy)
                saved += 1
        except Exception as exc:
            raise SharedUploadIncomplete(saved, created, len(files), str(exc)) from exc
        return {'files_uploaded': saved, 'folders_created': created, 'files_skipped': skipped}
