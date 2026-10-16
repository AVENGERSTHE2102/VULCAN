"""Reset an existing local browser session; keys are never read by this script."""

import argparse
import getpass
from urllib.parse import urlsplit
import httpx


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://localhost:8080")
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument("--mission", type=int, choices=range(1, 8))
    choice.add_argument(
        "--all",
        action="store_true",
        help="Clear session synthetic state, evidence, keys and budgets",
    )
    a = p.parse_args()
    if urlsplit(a.url).hostname not in ("localhost", "127.0.0.1"):
        p.error("Use a local lab URL")
    cookie = getpass.getpass("Local vulcan_session cookie: ")
    if len(cookie) != 32 or not all(c in "0123456789abcdef" for c in cookie):
        p.error("Invalid session cookie")
    with httpx.Client(
        base_url=a.url, cookies={"vulcan_session": cookie}, trust_env=False
    ) as c:
        r = c.post("/api/reset" if a.all else f"/api/missions/{a.mission}/reset")
        r.raise_for_status()
        print(r.json())


if __name__ == "__main__":
    main()
