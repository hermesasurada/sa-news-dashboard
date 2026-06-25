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
from pathlib import Path
from typing import Optional, Dict, Any

from curl_cffi import requests as curl_requests
# playwright는 lazy import (parse_with_playwright_stealth 내부).
# system python처럼 playwright 미설치 환경에서도 Jina/curl_cffi fallback이 동작하도록 모듈 로드를 막지 않음.

PW_PROFILE_DIR = str(Path(__file__).resolve().parent / "pw_profile")

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
            headers={
                "Accept": "application/json",
                "User-Agent": UA,
                # #2: 기사 element만 추출 → SA 네비게이션 ~14000자 제거.
                # SA 뉴스 본문은 <article>에 H1·날짜·종목태그(TSLA 등)와 함께 담김.
                "X-Target-Selector": "article",
            },
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

        # #2: X-Target-Selector=article로 이미 기사 element만 받으므로
        # 기존의 "title 2번째 등장" nav-제거 휴리스틱은 불필요(오히려 본문을 잘못 자름).
        # article 안의 'recommended for you' 링크는 보통 본문 뒤라 앞에서 10000자 자르면 본문이 들어옴.
        body = content_md[:10000]
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


def _og_lead(url: str) -> str:
    """SA 페이지 정적 메타(og:title/og:description)에서 깔끔한 리드 추출.
    어떤 본문 파서가 이기든 핵심 종목이 담긴 리드를 보장하기 위함 (#1).
    실패해도 빈 문자열 → 호출측 무해."""
    try:
        r = curl_requests.get(url, headers={"User-Agent": UA}, impersonate="chrome124", timeout=20)
        if r.status_code != 200:
            return ""
        html_text = r.text
        def _meta(prop):
            m = re.search(
                r'<meta[^>]*property=["\']og:' + prop + r'["\'][^>]*content=["\']([^"\']*)["\']',
                html_text)
            if not m:
                m = re.search(
                    r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*property=["\']og:' + prop + r'["\']',
                    html_text)
            return html.unescape(m.group(1).strip()) if m else ""
        title = _meta("title")
        desc = _meta("description")
        lead = "\n".join(x for x in (title, desc) if x)
        return lead.strip()
    except Exception:
        return ""


def parse_sa_article(url: str) -> Dict[str, Any]:
    """SA 기사 파싱 (3단계 Fallback, 인증 없음).

    Returns:
        {
            "success": bool,
            "title": str,
            "content": str,           # 본문 (요약 재료) — 앞에 og 리드 prepend
            "method": str or None,
            "error": str or None
        }
    """
    url = strip_utm(url)
    lead = _og_lead(url)  # #1: 핵심 종목이 담긴 리드 (본문 앞에 붙임)
    # 우선순위 (v5 — Jina 우선): 로컬 IP 평판 소모 방지
    for parser in [parse_with_jina_reader, parse_with_playwright_stealth, parse_with_curl_cffi_rotated]:
        result = parser(url)
        if result:
            body = result.get("content", "")
            # 핵심 종목이 담긴 og 리드를 항상 본문 앞에 prepend (어떤 파서가 이기든 보장).
            # 단, 리드 끝부분(설명 핵심)이 이미 본문에 있으면 중복 회피.
            if lead and (len(lead) < 40 or lead[-40:] not in body):
                result["content"] = f"{lead}\n\n{body}"
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
