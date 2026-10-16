"""Run vulnerable/hardened acceptance against actual local HTTP services (no keys)."""

import argparse
import time
from urllib.parse import urlsplit
import httpx


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://127.0.0.1:8000")
    a = p.parse_args()
    if urlsplit(a.url).hostname not in ("localhost", "127.0.0.1"):
        p.error("Use a local lab URL")
    with httpx.Client(base_url=a.url, trust_env=False) as c:
        c.get("/api/session").raise_for_status()
        c.post("/api/settings", json={"offline": True}).raise_for_status()
        for mode in ("vulnerable", "hardened"):
            c.post("/api/config/" + mode).raise_for_status()
            for mission in range(1, 8):
                before = time.monotonic()
                c.post(f"/api/missions/{mission}/reset").raise_for_status()
                reset = time.monotonic() - before
                assert reset < 10
                r = c.post(f"/api/missions/{mission}/run", json={"mode": "live"})
                r.raise_for_status()
                tid = r.json()["id"]
                deadline = time.monotonic() + 20
                while True:
                    t = c.get("/api/tasks/" + tid).json()
                    if t["status"] in ("completed", "failed", "limit"):
                        break
                    assert time.monotonic() < deadline, "Task did not settle"
                    time.sleep(0.05)
                assert t["legitimate_success"], t
                assert t["attack_success"] == (mode == "vulnerable"), t
                assert t["source"] == "Scripted"
                if mission == 6:
                    assert "mode" in t["inspection"]
                print(f"M{mission} {mode}: pass; reset {reset:.3f}s")
        assert c.get("/api/settings").json()["requests"] == 0
        c.post("/api/reset").raise_for_status()


if __name__ == "__main__":
    main()
