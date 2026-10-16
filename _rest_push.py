"""Push changed files to GitHub via the REST Contents API.

Bypasses the git CONNECT tunnel that is currently unreliable in the sandbox.
For each file: fetch its current SHA (so the PUT is an update), then PUT the
new base64 content. Creates a commit per file for clarity.
"""
import base64
import json
import subprocess
import sys
from pathlib import Path

REPO = "yyf127/QuickPythonIDE"
BRANCH = "main"
ROOT = Path(__file__).resolve().parent

FILES = [
    "main.py",
    "tests/test_api.py",
    "ui/index.html",
    "ui/css/style.css",
    "ui/js/main.js",
]

MSG = "Stage 3: subprocess-isolated runner + stop, python version switch, pip install, backup"


def gh_token() -> str:
    out = subprocess.run(
        [r"C:\Program Files\GitHub CLI\gh.exe", "auth", "token"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def api(method: str, path: str, token: str, payload: dict | None = None) -> dict | None:
    import urllib.request
    url = f"https://api.github.com{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "quickpythonide-push")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode()[:300]}")


def main() -> None:
    token = gh_token()
    for rel in FILES:
        local = ROOT / rel
        content_b64 = base64.b64encode(local.read_bytes()).decode()
        # fetch current sha
        info = api("GET", f"/repos/{REPO}/contents/{rel}?ref={BRANCH}", token)
        sha = info.get("sha") if info else None
        payload = {
            "message": MSG,
            "content": content_b64,
            "branch": BRANCH,
        }
        if sha:
            payload["sha"] = sha
        res = api("PUT", f"/repos/{REPO}/contents/{rel}", token, payload)
        if res and res.get("commit"):
            print(f"OK  {rel} -> {res['commit']['sha'][:10]}")
        else:
            print(f"FAIL {rel}: {res}", file=sys.stderr)
            raise SystemExit(1)


if __name__ == "__main__":
    main()
