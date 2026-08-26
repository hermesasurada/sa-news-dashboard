#!/usr/bin/env python3
"""Seeking Alpha 로그인 세션을 sa_cookies.json에 저장한다.

Playwright 번들 Chromium은 SA PerimeterX가 봇으로 막는다
('To continue, please prove you are not a robot').
설치된 Google Chrome을 headed로 연다. 평소 쓰는 Chrome 프로필은 건드리지 않고
pw_login_profile/ 만 사용한다.

브라우저에서 로그인한 뒤 이 터미널에서 Enter.
비밀번호는 저장하지 않고 쿠키만 덤프한다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sa_article_parser import COOKIES_PATH, has_login_cookies  # noqa: E402

LOGIN_PROFILE_DIR = REPO_ROOT / "pw_login_profile"
VENV_PYTHON = REPO_ROOT / "venv" / "bin" / "python3"


def _reexec_in_venv() -> None:
    """venv 밖에서 실행되면 venv 파이썬으로 다시 띄운다.

    playwright는 venv에만 설치돼 있어서 `python3 scripts/sa_refresh_login.py`로
    실행하면 ImportError가 난다. 사용자가 인터프리터를 신경 쓰지 않아도 되도록
    여기서 스스로 갈아탄다.

    이미 venv인지는 sys.prefix로 본다. venv/bin/python3는 시스템 파이썬을 가리키는
    심링크라 sys.executable을 resolve()해 비교하면 둘이 같아져 재실행이 안 된다."""
    try:
        if not VENV_PYTHON.is_file():
            return
        if Path(sys.prefix).resolve() == (REPO_ROOT / "venv").resolve():
            return  # 이미 venv — 무한 재실행 방지
        script = str(Path(__file__).resolve())
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), script, *sys.argv[1:]])
    except Exception:
        return  # 재실행에 실패해도 아래 ImportError 안내로 이어진다


def main() -> int:
    _reexec_in_venv()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            f"playwright 패키지가 없습니다 (현재 인터프리터: {sys.executable}).\n"
            f"venv 파이썬으로 실행하세요:\n"
            f"  {VENV_PYTHON} {Path(__file__).resolve()}",
            file=sys.stderr,
        )
        return 1

    dest = Path(COOKIES_PATH)
    LOGIN_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("Google Chrome이 열립니다. Seeking Alpha에 로그인한 뒤 이 창에서 Enter.")
    print("로봇 확인이 뜨면 Chrome에서 직접 통과한 다음 로그인하세요.")
    print("쿠키만 sa_cookies.json에 저장합니다. 비밀번호는 저장하지 않습니다.")
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(LOGIN_PROFILE_DIR),
                channel="chrome",
                headless=False,
                ignore_default_args=["--enable-automation"],
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1280, "height": 840},
                locale="en-US",
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://seekingalpha.com/", timeout=60000, wait_until="domcontentloaded")
            try:
                input()
            except EOFError:
                print("입력 없이 종료되었습니다.", file=sys.stderr)
                ctx.close()
                return 1
            cookies = ctx.cookies()
            ctx.close()
    except Exception as exc:
        print(f"브라우저를 열 수 없습니다: {exc}", file=sys.stderr)
        print("Google Chrome이 설치되어 있는지 확인하세요.", file=sys.stderr)
        return 1

    dest.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    login = has_login_cookies(cookies)
    print(f"저장 {dest} · 쿠키 {len(cookies)}개 · 로그인 표지 {'있음' if login else '없음'}")
    if not login:
        print("user_id / user_remember_token 이 없습니다. 로그인이 끝났는지 확인하세요.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
