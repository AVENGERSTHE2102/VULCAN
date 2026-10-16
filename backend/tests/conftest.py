import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from fastapi.testclient import TestClient
from lab.api import create_app
from lab.store import Store
from lab.policy import Config
from lab.providers import Planners


@pytest.fixture
def app(tmp_path):
    return create_app(Store(":memory:"), Config(tmp_path / "active.yaml"), Planners())


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.get("/api/session")
        yield c
