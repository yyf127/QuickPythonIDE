"""通过 GitHub REST Contents API 推送单个文件（绕过 git CONNECT 隧道）。

用法：python _rest_push.py <repo相对路径> [<repo相对路径> ...]
需要环境变量或运行时提供 token；这里直接用 gh 取 token。
"""
import base64
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

REPO = "yyf127/QuickPythonIDE"
API = f"https://api.github.com/repos/{REPO}/contents"


def gh_token() -> str:
    out = subprocess.run(
        [r"C:\Program Files\GitHub CLI\gh.exe", "auth", "token"],
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def push(local_path: str, repo_path: str, token: str) -> None:
    url = f"{API}/{repo_path}"
    # 取当前 blob sha（存在才需要，用于更新）
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    })
    sha = None
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
            sha = data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise

    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    body = {
        "message": f"feat: adapt to root/ embedded interpreters + project/ tree root",
        "content": content,
    }
    if sha:
        body["sha"] = sha

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"pushed {repo_path}: {r.status}")


def main() -> None:
    token = gh_token()
    for arg in sys.argv[1:]:
        # 本地路径即仓库相对路径（工作区根 = 仓库根）
        push(arg, arg, token)


if __name__ == "__main__":
    main()
