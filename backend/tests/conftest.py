"""Keep import-time Client and Server state in a temporary directory."""

import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    sandbox = tempfile.TemporaryDirectory(prefix='rch-tests-')
    config.add_cleanup(sandbox.cleanup)
    root = Path(sandbox.name)
    client = root / 'client'
    client.mkdir()

    settings = pytest.MonkeyPatch()
    config.add_cleanup(settings.undo)
    settings.setenv('RCH_SERVER_RUNTIME_DIR', str(root / 'server'))
    settings.delenv('RCH_DOCUMENT_ROOTS', raising=False)
    settings.setattr(tempfile, 'tempdir', str(client))
