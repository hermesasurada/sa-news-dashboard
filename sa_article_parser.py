#!/usr/bin/env python3
"""
SA 기사 파서 (3단계 Fallback, 인증 없음)

Fallback 순서 (v5 — Jina 우선):
1. Jina Reader (r.jina.ai) — 외부 reader proxy. 우리 로컬 IP 평판 보호.
2. Playwright stealth + persistent profile (누적 브라우저 상태)
3. curl_cffi impersonate 로테이션 (chrome124 → safari17_2 → edge99)

세션 쿠키/Google OAuth 의존성 제거. 모든 단계가 인증 없이 동작.

이유: Playwright/curl_cffi가 우리 단일 로컬 IP를 사용 → 차단되면 다음 시도도 같은 IP라
무용지물. Jina는 자체 인프라(분리된 IP pool)라 1순위로 시도해 로컬 평판을 보전.
"""

import html
import json
import os
import re
import time
from typing import Optional, Dict, Any

from curl_cffi import requests as curl_requests
# playwright는 lazy import (parse_with_playwright_stealth 내부).
# system python처럼 playwright 미설치 환경에서도 Jina/curl_cffi fallback이 동작하도록 모듈 로드를 막지 않음.

PW_PROFILE_DIR = "/Users/yhandhs/Documents/sa-dashboard/pw_profile"

STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};
Object.defineProperty(navigator, 'permissions', {
    get: () => ({query: () => Promise.resolve({state: 'granted'})})
});
"""

IMPERSONATES = ["chrome124", "safari17_2", "edge99"]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def strip_utm(url: str) -> str:
    """article_url에서 utm_content, position 파라미터 제거."""
    from urllib.parse import unquote
    decoded = unquote(url)
    if '?' not in decoded:
        return decoded
    base, query = decoded.split('?', 1)
    params = [p for p in query.split('&') if p and not p.startswith('utm_content') and not p.startswith('position')]
    return base + '?' + '&'.join(params) if params else base


def _extract_content(html_content: str) -> str:
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_content, re.DOTALL)
    title = title_match.group(1).strip() if title_match else ""

    # JSON-LD description 추출 (본문보다 풍부한 메타데이터 포함)
    json_ld_desc = ""
    json_lds = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_content, re.DOTALL)
    for jld in json_lds:
        try:
            data = json.loads(jld)
            if isinstance(data, dict) and data.get("@type") == "NewsArticle":
                desc = data.get("description", "")
                if desc and len(desc) > 50:
                    json_ld_desc = desc
                    break
        except Exception:
            pass

    # <article> 태그 안의 <p>만 추출 (네비게이션 제외)
    article_match = re.search(r"<article[^>]*>(.*?)</article>", html_content, re.DOTALL)
    if article_match:
        article_body = article_match.group(1)
        raw_paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", article_body, re.DOTALL)
    else:
        raw_paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html_content, re.DOTALL)

    clean_paragraphs = []
    for p in raw_paragraphs:
        text = re.sub(r'<[^>]+>', '', p)
        text = html.unescape(text)
        text = text.strip()
        if len(text) > 30:
            clean_paragraphs.append(text)
    selected = clean_paragraphs[:30]
    if len(selected) < 15 and len(clean_paragraphs) > 15:
        selected = clean_paragraphs[:15]
    body_text = " ".join(selected)

    if json_ld_desc:
        full_content = f"{title}\n\n{json_ld_desc}\n\n{body_text}"
    else:
        full_content = f"{title}\n\n{body_text}"

    return full_content[:10000]


def _is_blocked(html_content: str) -> bool:
    if len(html_content) < 9000:
        return True
    if "Access to this page has been denied" in html_content:
        return True
    # SVG-only false positive: <path>가 대량이고 본문 텍스트 부족
    text_only = re.sub(r'<[^>]+>', '', html_content)
    if len(text_only.strip()) < 800 and html_content.count('<path') > 20:
        return True
    return False


def _parse_html(html_content: str, method: str) -> Optional[Dict[str, Any]]:
    if _is_blocked(html_content):
        return None
    title_match = re.search(r"<title>(.*?)</title>", html_content)
    return {
        "title": title_match.group(1) if title_match else "",
        "content": _extract_content(html_content),
        "method": method,
    }


def parse_with_playwright_stealth(url: str) -> Optional[Dict[str, Any]]:
    """1단계: Playwright + stealth init + persistent profile (인증 없음)

    누적된 브라우저 상태(LocalStorage/IndexedDB/cookies)가 프로필 디렉토리에
    저장되어 다음 실행에서도 재사용됨. PerimeterX의 fingerprint-based 신뢰도
    축적에 유리.
    """
    try:
        from playwright.sync_api import sync_playwright  # lazy: 미설치 시 이 fallback만 건너뜀
    except ImportError:
        return None
    try:
        os.makedirs(PW_PROFILE_DIR, exist_ok=True)
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=PW_PROFILE_DIR,
                headless=True,
                user_agent=UA,
            )
            ctx.add_init_script(STEALTH_INIT)
            page = ctx.new_page()
            page.goto(url, timeout=25000, wait_until="load")
            time.sleep(2)
            html_content = page.content()
            ctx.close()
        return _parse_html(html_content, "playwright_stealth")
    except Exception:
        return None


def parse_with_jina_reader(url: str) -> Optional[Dict[str, Any]]:
    """2단계: Jina Reader (r.jina.ai) — 외부 reader proxy.

    Jina 서버가 대신 페이지를 가져와 markdown으로 반환. PerimeterX를 그쪽에서
    처리하므로 우리 IP/fingerprint와 무관. 무료 tier: ~20 RPM.
    """
    try:
        resp = curl_requests.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=25,
        )
        if resp.status_code != 200:
            return None

        title = ""
        content_md = ""
        try:
            data = resp.json()
            payload = data.get("data") if isinstance(data, dict) else None
            if isinstance(payload, dict):
                title = payload.get("title") or ""
                content_md = payload.get("content") or ""
        except Exception:
            pass

        if not content_md:
            # 폴백: text/markdown 헤더 응답 파싱
            text = resp.text
            title_m = re.search(r"^Title:\s*(.+)$", text, re.MULTILINE)
            content_m = re.search(r"Markdown Content:\s*\n(.*)", text, re.DOTALL)
            title = title_m.group(1).strip() if title_m else title
            content_md = content_m.group(1).strip() if content_m else text

        if len(content_md) < 500:
            return None
        if "Access to this page has been denied" in content_md:
            return None

        # 본문 시작점 찾기: Jina markdown은 보통
        #   "# {title} | Seeking Alpha" (페이지 헤더) → 사이트 네비게이션 ~14000자 → "# {title}" (article H1) → 본문
        # 형태. title이 두 번째 등장하는 위치부터 잘라야 nav가 잘려서 10000자 윈도우에 본문이 들어옴.
        # title 매칭에는 첫 60자만 사용 (Jina가 "| Seeking Alpha" 등 suffix를 붙이거나 일부 변형할 수 있음).
        start = 0
        if title:
            needle = title[:60]
            first = content_md.find(needle)
            if first >= 0:
                second = content_md.find(needle, first + len(needle))
                if second > 0:
                    start = second
        body = content_md[start:start + 10000]
        if title and not body.lstrip().startswith(title[:30]):
            body = f"{title}\n\n{body}"[:10000]
        return {
            "title": title,
            "content": body,
            "method": "jina_reader",
        }
    except Exception:
        return None


def parse_with_curl_cffi_rotated(url: str) -> Optional[Dict[str, Any]]:
    """3단계: curl_cffi impersonate 로테이션.

    같은 라이브러리지만 TLS/JA3 fingerprint를 다양화. PerimeterX의
    fingerprint 패턴 학습 회피.
    """
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://www.google.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
    }
    for imp in IMPERSONATES:
        try:
            resp = curl_requests.get(url, headers=headers, impersonate=imp, timeout=30)
            if resp.status_code == 200:
                result = _parse_html(resp.text, f"curl_cffi_{imp}")
                if result:
                    return result
        except Exception:
            pass
        time.sleep(2)
    return None


def parse_sa_article(url: str) -> Dict[str, Any]:
    """SA 기사 파싱 (3단계 Fallback, 인증 없음).

    Returns:
        {
            "success": bool,
            "title": str,
            "content": str,           # 본문 (요약 재료)
            "method": str or None,
            "error": str or None
        }
    """
    url = strip_utm(url)
    # 우선순위 (v5 — Jina 우선): 로컬 IP 평판 소모 방지
    for parser in [parse_with_jina_reader, parse_with_playwright_stealth, parse_with_curl_cffi_rotated]:
        result = parser(url)
        if result:
            result["success"] = True
            result["error"] = None
            return result

    return {
        "success": False,
        "title": "",
        "content": "",
        "method": None,
        "error": "All 3 methods failed (strong block or transient failure)",
    }


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://seekingalpha.com/news/4594420-mythos-drives-potential-upside-for-cybersecurity-firms-ahead-of-earnings-keybanc"
    print(f"URL: {url}\n" + "-" * 60)
    res = parse_sa_article(url)
    if res["success"]:
        print(f"OK (method: {res['method']})")
        print(f"Title: {res['title'][:80]}")
        print(f"Content length: {len(res['content'])} chars")
        print(f"\nPreview:\n{res['content'][:500]}")
    else:
        print(f"FAIL: {res['error']}")
