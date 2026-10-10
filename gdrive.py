"""구글 드라이브 연동 — Grok Bot과 기사 원문을 주고받는 통로(2026-10-11 사용자 결정).

sa는 SA 사이트에 직접 접속하지 않는다. 대신 드라이브 폴더 'SA Grok'에
  requests/req_*.json  ← sa가 올리는 읽을 기사 목록(news_id, url)
  results/sa_<id>.json ← Grok Bot이 올리는 기사 원문
을 두고 주고받는다.

권한은 두 가지만 쓴다(설치형 앱 OAuth, hermes-blogger와 같은 클라이언트):
  - drive.file     : sa가 만든 폴더·요청 파일 쓰기
  - drive.readonly : Grok Bot이 올린 결과 파일 읽기
토큰은 ~/.hermes/gdrive_token.json(권한 600). 최초 1회 사용자가 브라우저에서 동의한다:

  venv/bin/python gdrive.py auth     # 브라우저 동의(Grok Bot이 쓰는 그 구글 계정으로)
  venv/bin/python gdrive.py whoami   # 연결된 계정 확인
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

CLIENT_SECRET_PATH = Path(os.environ.get("SA_GDRIVE_CLIENT", "~/.hermes/blogger_client_secret.json")).expanduser()
TOKEN_PATH = Path(os.environ.get("SA_GDRIVE_TOKEN", "~/.hermes/gdrive_token.json")).expanduser()
SCOPES = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"


class DriveError(RuntimeError):
    pass


def _http_json(method: str, url: str, *, form: dict | None = None, body: dict | None = None,
               headers: dict | None = None) -> dict:
    data = None
    hdr = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdr["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdr, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(raw).get("error")
            msg = msg.get("message") if isinstance(msg, dict) else msg
        except Exception:
            msg = raw[:300]
        raise DriveError(f"HTTP {e.code}: {msg}") from None
    except urllib.error.URLError as e:
        raise DriveError(f"네트워크 오류: {e.reason}") from None


def _client() -> dict:
    try:
        d = json.loads(CLIENT_SECRET_PATH.read_text(encoding="utf-8"))
    except OSError:
        raise DriveError(f"OAuth 클라이언트 파일 없음: {CLIENT_SECRET_PATH}")
    d = d.get("installed") or d.get("web") or d
    if not d.get("client_id") or not d.get("client_secret"):
        raise DriveError("client_secret 형식이 아닙니다")
    return d


def _write_token(tok: dict) -> None:
    tmp = TOKEN_PATH.with_name(TOKEN_PATH.name + ".tmp")
    tmp.write_text(json.dumps(tok), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(TOKEN_PATH)


def configured() -> bool:
    try:
        return bool(json.loads(TOKEN_PATH.read_text(encoding="utf-8")).get("refresh_token"))
    except Exception:
        return False


def auth(open_browser: bool = True) -> dict:
    """설치형 앱 플로우(PKCE + 루프백). 사용자가 브라우저에서 동의 → 토큰 저장."""
    cl = _client()
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>드라이브 연결 완료 — 이 창을 닫아도 됩니다.</h2>".encode("utf-8"))

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_address[1]}/"
    url = AUTH_URI + "?" + urllib.parse.urlencode({
        "client_id": cl["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent select_account", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    print("브라우저에서 Grok Bot이 쓰는 구글 계정으로 동의해 주세요. 열리지 않으면 이 URL을 여세요:\n" + url,
          flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    t.join(600)
    srv.server_close()
    if got.get("state") != state or not got.get("code"):
        raise DriveError(f"동의 응답을 받지 못했습니다(시간 초과 또는 거부: {got.get('error', '')})")
    tok = _http_json("POST", cl.get("token_uri", TOKEN_URI), form={
        "code": got["code"], "client_id": cl["client_id"], "client_secret": cl["client_secret"],
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier,
    })
    if not tok.get("refresh_token"):
        raise DriveError("refresh_token이 없습니다 — 동의를 다시 진행해 주세요")
    saved = {"client_id": cl["client_id"], "client_secret": cl["client_secret"],
             "refresh_token": tok["refresh_token"], "access_token": tok.get("access_token", ""),
             "expires_at": time.time() + int(tok.get("expires_in", 0)) - 60, "scope": tok.get("scope", "")}
    _write_token(saved)
    return saved


def access_token() -> str:
    if not configured():
        raise DriveError("드라이브 미연결 — `venv/bin/python gdrive.py auth`를 먼저 실행하세요")
    lock_path = str(TOKEN_PATH) + ".lock"
    with open(lock_path, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            tok = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
            if tok.get("access_token") and time.time() < float(tok.get("expires_at", 0)):
                return tok["access_token"]
            fresh = _http_json("POST", TOKEN_URI, form={
                "client_id": tok["client_id"], "client_secret": tok["client_secret"],
                "refresh_token": tok["refresh_token"], "grant_type": "refresh_token",
            })
            tok["access_token"] = fresh["access_token"]
            tok["expires_at"] = time.time() + int(fresh.get("expires_in", 3600)) - 60
            _write_token(tok)
            return tok["access_token"]
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def api(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    return _http_json(method, url, body=body, headers={"Authorization": f"Bearer {access_token()}"})


FOLDER_MIME = "application/vnd.google-apps.folder"


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_folder(name: str, parent: str = "root") -> str | None:
    q = f"name = '{_q(name)}' and mimeType = '{FOLDER_MIME}' and '{parent}' in parents and trashed = false"
    files = api("GET", "/files", {"q": q, "fields": "files(id,name)", "pageSize": 10}).get("files") or []
    return files[0]["id"] if files else None


def ensure_folder(name: str, parent: str = "root") -> str:
    fid = find_folder(name, parent)
    if fid:
        return fid
    return api("POST", "/files", {"fields": "id"},
               body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent]})["id"]


def list_children(parent: str, name_prefix: str = "") -> list[dict]:
    """폴더 안 파일 목록(id, name, modifiedTime). 이름 접두어로 거른다."""
    q = f"'{parent}' in parents and trashed = false and mimeType != '{FOLDER_MIME}'"
    if name_prefix:
        q += f" and name contains '{_q(name_prefix)}'"
    out, token = [], None
    while True:
        params = {"q": q, "fields": "nextPageToken,files(id,name,modifiedTime)", "pageSize": 1000}
        if token:
            params["pageToken"] = token
        res = api("GET", "/files", params)
        out += [f for f in res.get("files") or [] if f.get("name", "").startswith(name_prefix)]
        token = res.get("nextPageToken")
        if not token:
            return out


def download_text(file_id: str) -> str:
    req = urllib.request.Request(f"{API}/files/{file_id}?alt=media",
                                 headers={"Authorization": f"Bearer {access_token()}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8-sig", "replace")
    except urllib.error.HTTPError as e:
        raise DriveError(f"HTTP {e.code}: {e.read()[:200]!r}") from None
    except urllib.error.URLError as e:
        raise DriveError(f"네트워크 오류: {e.reason}") from None


def upload_json(name: str, parent: str, obj) -> str:
    """JSON 파일을 새로 만든다(멀티파트 업로드). 파일 id를 돌려준다."""
    boundary = "sa" + secrets.token_hex(12)
    meta = json.dumps({"name": name, "parents": [parent], "mimeType": "application/json"})
    content = json.dumps(obj, ensure_ascii=False, indent=1)
    data = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{content}\r\n"
            f"--{boundary}--\r\n").encode("utf-8")
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id", data=data,
        headers={"Authorization": f"Bearer {access_token()}",
                 "Content-Type": f"multipart/related; boundary={boundary}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())["id"]
    except urllib.error.HTTPError as e:
        raise DriveError(f"HTTP {e.code}: {e.read()[:200]!r}") from None
    except urllib.error.URLError as e:
        raise DriveError(f"네트워크 오류: {e.reason}") from None


def delete_file(file_id: str) -> None:
    api("DELETE", f"/files/{file_id}")


def whoami() -> str:
    return (api("GET", "/about", {"fields": "user(emailAddress,displayName)"}).get("user") or {}).get(
        "emailAddress", "")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "whoami"
    try:
        if cmd == "auth":
            auth()
            print("연결됨:", whoami())
        elif cmd == "whoami":
            print(whoami())
        else:
            print(__doc__)
            return 2
    except DriveError as e:
        print("오류:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
