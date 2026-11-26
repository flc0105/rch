from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import io
from pathlib import Path

import pytest
from server.application.transfers.upload_budget import UploadBudget


def test_global_byte_and_owner_limits_release_exactly_once():
    budget = UploadBudget(max_bytes=100, max_slots=3, max_owner_slots=1)
    a = budget.acquire(60, 'device-a')
    with pytest.raises(ValueError, match='Device'):
        budget.acquire(1, 'device-a')
    with pytest.raises(ValueError, match='byte limit'):
        budget.acquire(41, 'device-b')
    with budget.reserve(40):
        with pytest.raises(ValueError, match='byte limit'):
            budget.acquire(1)
    budget.release(a)
    budget.release(a)
    with budget.reserve(100):
        pass


def test_concurrent_intake_admission_never_overcommits():
    budget = UploadBudget(max_bytes=10, max_slots=2, max_owner_slots=2)
    barrier = Barrier(8)
    def try_reserve(i):
        try:
            token = budget.acquire(5)
        except ValueError:
            token = None
        barrier.wait(timeout=5)
        if token is not None:
            budget.release(token)
        return token is not None
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(try_reserve, range(8))) == 2
    with budget.reserve(10):
        pass


def test_slot_limit_applies_even_to_empty_uploads_and_failure_releases():
    budget = UploadBudget(max_bytes=1, max_slots=1, max_owner_slots=1)
    with pytest.raises(RuntimeError):
        with budget.reserve(0):
            with pytest.raises(ValueError, match='concurrency'):
                budget.acquire(0)
            raise RuntimeError('simulated failure')
    with budget.reserve(1):
        pass


def test_staging_lease_lives_until_cleanup_and_shared_intake_uses_same_budget(tmp_path):
    pytest.importorskip('werkzeug')
    from server.application.artifact.artifact_temp_file_service import ArtifactTempFileService
    budget = UploadBudget(max_bytes=10, max_slots=2, max_owner_slots=1)
    service = ArtifactTempFileService(SimpleNamespace(upload_tmp_dir=str(tmp_path)), budget=budget)
    path, _ = service.create_upload_temp_path('f.txt', expected_size=8, owner='device')
    Path(path).write_bytes(b'12345678')
    with pytest.raises(ValueError, match='byte limit'):
        with service.reserve_intake(3):
            pass
    service.cleanup_temp_file(path)
    with service.reserve_intake(10):
        pass
    upload = SimpleNamespace(filename='new', stream=io.BytesIO(b'hello'))
    path, _ = service.create_upload_temp_file(upload)
    assert Path(path).read_bytes() == b'hello'
    service.cleanup_temp_file(path)
    assert not list(tmp_path.iterdir())
