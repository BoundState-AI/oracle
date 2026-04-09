import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def workspace_tmp_path() -> Path:
    root = Path("tests/.tmp/runtime")
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
