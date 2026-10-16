import sys
import httpx
import pytest
import yaml
from lab.policy import load_snapshot
from scripts import calibrate


def test_calibration_rejects_scripted_trial(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "calibrate",
            "--mission",
            "1",
            "--provider",
            "groq",
            "--trials",
            "1",
            "--output",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(calibrate.getpass, "getpass", lambda _: "a" * 32)

    def handler(request):
        path = request.url.path
        if path == "/api/settings":
            data = {
                "providers": [{"name": "groq", "configured": True}],
                "offline": False,
                "ollama": False,
            }
        elif path == "/api/config":
            data = {"yaml": yaml.safe_dump(load_snapshot("vulnerable"))}
        elif path == "/api/config/vulnerable":
            data = {"rules": load_snapshot("vulnerable")}
        elif path.endswith("/run"):
            data = {"id": "trial"}
        elif path == "/api/tasks/trial":
            data = {
                "status": "completed",
                "attack_success": True,
                "legitimate_success": True,
                "provider": "scripted",
                "model": "fixture",
            }
        elif path.endswith("/recording"):
            data = {"genuine": False, "turns": []}
        else:
            data = {}
        return httpx.Response(200, json=data)

    original = httpx.Client
    monkeypatch.setattr(
        calibrate.httpx,
        "Client",
        lambda **kw: original(**kw, transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RuntimeError, match="fell back"):
        calibrate.main()
    import json

    summary = json.loads((tmp_path / "m1-summary.json").read_text())
    assert summary["recordings"] == 0 and summary["release_gate"] is False
    assert summary["vulnerable_attack_rate"] is None
    assert not list(tmp_path.glob("*live*.json"))
