"""Python source Bundle builder."""
import os
import zipfile

from core.client_revision import CLIENT_BUNDLE_SOURCE_PATHS
from server.application.agent.agent_build_utils import copy_source_paths, inject_python_client_config


BUNDLE_INCLUDE_PATHS = CLIENT_BUNDLE_SOURCE_PATHS


class BundleBuilder:
    BUILD_STATUS_MESSAGE = 'Build completed.'

    def __init__(self, source_dir: str):
        self.source_dir = source_dir

    def build(self, *, work_dir: str, server_host: str, server_port: int,
              web_port: int, file_transfer_port: int, build_id: str, build_version: str,
              target_os: str, target_arch: str,
              server_web_scheme: str = 'http', server_web_host: str = '') -> dict:
        # Bundle is platform-independent; target_os and target_arch are only for
        # the common builder dispatch interface.
        staging_dir = os.path.join(work_dir, 'bundle')
        copy_source_paths(self.source_dir, BUNDLE_INCLUDE_PATHS, staging_dir)

        inject_python_client_config(
            self.source_dir, staging_dir,
            server_host,
            server_port,
            web_port,
            file_transfer_port,
            build_version,
            server_web_scheme,
            server_web_host,
        )
        bundle_name = f'rchclient-source-bundle-{build_id}.zip'
        bundle_path = os.path.join(work_dir, bundle_name)

        with zipfile.ZipFile(bundle_path, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
            for relative_path in BUNDLE_INCLUDE_PATHS:
                source_path = os.path.join(staging_dir, relative_path)
                if os.path.isdir(source_path):
                    for root, _, files in os.walk(source_path):
                        for filename in files:
                            file_path = os.path.join(root, filename)
                            arcname = os.path.relpath(file_path, staging_dir)
                            archive.write(file_path, arcname=arcname)
                else:
                    archive.write(source_path, arcname=relative_path)

        return {
            'file_path': bundle_path,
            'file_name': bundle_name,
            'warnings': [self.BUILD_STATUS_MESSAGE],
            'target_arch': 'n/a',
            'target_os': 'bundle',
        }
