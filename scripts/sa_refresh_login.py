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
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sa_article_parser import COOKIES_PATH, has_login_cookies  # noqa: E402

LOGIN_PROFILE_DIR = REPO_ROOT / "pw_login_profile"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 패키지가 없습니다. venv/bin/pip install playwright", file=sys.stderr)
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
