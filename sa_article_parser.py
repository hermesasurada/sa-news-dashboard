#!/usr/bin/env python3
"""
SA 기사 파서 (로그인 세션 우선, 실패 시 비로그인 폴백)

순서:
1. 로그인 쿠키 + Playwright persistent profile
2. 같은 쿠키 + curl_cffi HTML (짧은 본문은 폐기)
3. 같은 쿠키 + SA API. 미터링 페이월 프리뷰면 성공으로 치지 않음
4. Jina Reader
5. 비로그인 경로는 SA_ALLOW_ANON_FETCH 일 때만

쿠키는 `sa_cookies.json`(Playwright export 형식). 세션 갱신은
`scripts/sa_refresh_login.py`. 구독자가 볼 수 있는 본문만 가져오며
페이월을 우회하지 않는다.
"""

import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from curl_cffi import requests as curl_requests

import settings
# playwright는 lazy import (parse_with_playwright_stealth 내부).
# system python처럼 playwright 미설치 환경에서도 Jina/curl_cffi fallback이 동작하도록 모듈 로드를 막지 않음.

PW_PROFILE_DIR = str(Path(__file__).resolve().parent / "pw_profile")
COOKIES_PATH = Path(os.environ.get("SA_COOKIES_PATH") or Path(__file__).resolve().parent / "sa_cookies.json")
LOGIN_COOKIE_NAMES = {"user_remember_token", "user_id", "_sapi_session_id", "gk_user_access"}
AUTH_PREVIEW_LIMIT = 700

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


def cookies_path() -> Path:
    return Path(os.environ.get("SA_COOKIES_PATH") or COOKIES_PATH)


def load_sa_cookies() -> List[Dict[str, Any]]:
    """seekingalpha.com 쿠키만, 만료분은 제외. 값은 로그에 남기지 않는다."""
    path = cookies_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    now = time.time()
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "")
        if "seekingalpha.com" not in domain:
            continue
        exp = item.get("expires")
        if isinstance(exp, (int, float)) and exp > 0 and exp < now:
            continue
        name = item.get("name")
        value = item.get("value")
        if not name or value is None:
            continue
        same_site = item.get("sameSite") or "Lax"
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"
        cookie = {
            "name": str(name),
            "value": str(value),
            "domain": domain,
            "path": item.get("path") or "/",
            "httpOnly": bool(item.get("httpOnly")),
            "secure": bool(item.get("secure")),
            "sameSite": same_site,
        }
        if isinstance(exp, (int, float)) and exp > 0:
            cookie["expires"] = exp
        out.append(cookie)
    return out


def has_login_cookies(cookies: Iterable[Dict[str, Any]] | None = None) -> bool:
    cookies = list(cookies) if cookies is not None else load_sa_cookies()
    names = {c.get("name") for c in cookies}
    return bool(names & LOGIN_COOKIE_NAMES)


def cookie_header(cookies: Iterable[Dict[str, Any]]) -> str:
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))


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


def parse_with_sa_api(
    url: str,
    cookies: Optional[List[Dict[str, Any]]] = None,
    reject_locked_preview: bool = False,
) -> Optional[Dict[str, Any]]:
    """SA 내부 API /api/v3/news/{id}.

    페이지 HTML/Jina 대비 이점:
      (a) 네비게이션·'Recommended For You'·관련종목 노이즈 0 → 순수 본문만.
      (b) primaryTickers = SA가 직접 태깅한 후보 종목(심볼↔회사명 정확) 동봉.
    비로그인은 프리뷰(~300자). 로그인 쿠키를 붙여도 isMpwLocked면 같은
    프리뷰가 온다 — 그때는 성공으로 치지 않고 Playwright에 기회를 준다.
    news 형식이 아니거나(예: /article/) 응답 이상 시 None → 다음 폴백.
    """
    m = re.search(r'/news/(\d+)', url)
    if not m:
        return None
    nid = m.group(1)
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if cookies:
        headers["Cookie"] = cookie_header(cookies)
        headers["Referer"] = f"https://seekingalpha.com/news/{nid}"
    try:
        resp = curl_requests.get(
            f"https://seekingalpha.com/api/v3/news/{nid}?include=primaryTickers",
            headers=headers,
            impersonate="chrome124", timeout=25,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None

    node = data.get("data") or {}
    attrs = node.get("attributes") or {}
    body = html.unescape(re.sub(r"<[^>]+>", " ", attrs.get("content") or ""))
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) < 80:
        return None  # 본문 과소 → 폴백에 기회
    locked = bool(attrs.get("isMpwLocked") or attrs.get("isPaywalled") or attrs.get("isLockedPro"))
    title = (attrs.get("title") or "").strip()

    # primaryTickers → [{symbol, name}] (included의 tag 노드에서 해석)
    tickers = []
    rel = node.get("relationships") or {}
    prim_ids = [x.get("id") for x in ((rel.get("primaryTickers") or {}).get("data") or [])]
    inc = {(x.get("type"), x.get("id")): x for x in (data.get("included") or [])}
    for i in prim_ids:
        tag = inc.get(("tag", i)) or {}
        a = tag.get("attributes") or {}
        sym = (a.get("name") or "").strip()
        if sym:
            tickers.append({"symbol": sym, "name": (a.get("company") or "").strip()})

    full = f"{title}\n\n{body}" if title else body
    method = "sa_api_auth" if cookies else "sa_api"
    result = {
        "title": title,
        "content": full[:10000],
        "method": method,
        "tickers": tickers,
        "locked": locked,
    }
    if reject_locked_preview and locked and len(body) < AUTH_PREVIEW_LIMIT:
        result["rejected"] = True
    return result


def parse_with_playwright_stealth(
    url: str,
    cookies: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Playwright + stealth init + persistent profile.

    sa_cookies.json 로그인 쿠키가 있으면 페이지에 주입한다. 프로필 디렉토리의
    LocalStorage/IndexedDB도 재사용한다.
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
            if cookies:
                try:
                    ctx.add_cookies(cookies)
                except Exception:
                    pass
            page = ctx.new_page()
            # SA가 느릴 수 있어 로드 35s 허용. JS SPA라 본문은 load 이후 XHR로 렌더 → 3s 추가 대기.
            page.goto(url, timeout=35000, wait_until="load")
            time.sleep(3)
            html_content = page.content()
            ctx.close()
        method = "playwright_auth" if cookies else "playwright_stealth"
        result = _parse_html(html_content, method)
        if result:
            result["locked"] = len(result.get("content") or "") < AUTH_PREVIEW_LIMIT
        return result
    except Exception as exc:
        method = "playwright_auth" if cookies else "playwright_stealth"
        return {
            "method": method,
            "content": "",
            "locked": True,
            "error": f"{type(exc).__name__}: {exc}",
        }


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
            timeout=30,
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


def parse_with_curl_cffi_rotated(
    url: str,
    cookies: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """curl_cffi impersonate 로테이션. 로그인 쿠키가 있으면 Cookie 헤더를 붙인다."""
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
    if cookies:
        headers["Cookie"] = cookie_header(cookies)
        headers["Referer"] = "https://seekingalpha.com/"
    suffix = "_auth" if cookies else ""
    for imp in IMPERSONATES:
        try:
            resp = curl_requests.get(url, headers=headers, impersonate=imp, timeout=30)
            if resp.status_code == 200:
                result = _parse_html(resp.text, f"curl_cffi_{imp}{suffix}")
                if result:
                    if cookies and len(result.get("content") or "") < AUTH_PREVIEW_LIMIT:
                        continue
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


def _acceptable_source(result: Optional[Dict[str, Any]]) -> bool:
    """미리보기·잠금·파서 오류는 성공으로 치지 않는다."""
    if not result or result.get("rejected") or result.get("error"):
        return False
    content = (result.get("content") or "").strip()
    if len(content) < AUTH_PREVIEW_LIMIT:
        return False
    if result.get("locked"):
        return False
    return True


def _warn_no_login() -> None:
    """SA 로그인 세션이 없을 때 원인을 stderr로 표면화한다.

    쿠키 파일 유무로 '미설정'과 '만료/무효'를 구분해 안내한다.
    (load_sa_cookies가 만료분을 걸러내므로, 파일은 있는데 로그인 쿠키가 없으면 만료로 본다)
    """
    path = cookies_path()
    if not path.is_file():
        detail = f"쿠키 파일 없음 ({path})"
    else:
        detail = "로그인 쿠키 만료/무효"
    print(
        f"     ⚠️ SA 로그인 세션 없음 — {detail}. 본문이 프리뷰로 잘립니다. "
        f"복구: python3 scripts/sa_refresh_login.py",
        file=sys.stderr,
    )


def parse_sa_article(url: str) -> Dict[str, Any]:
    """SA 기사 파싱. Playwright 쿠키 세션을 먼저 시도한다.

    비로그인 API 미리보기는 기본 성공으로 치지 않는다.
    Returns 에 attempts(각 단계 결과)를 포함한다.
    """
    url = strip_utm(url)
    lead = _og_lead(url)
    cookies = load_sa_cookies()
    steps: List[tuple] = []
    if not has_login_cookies(cookies):
        # 인증 경로가 통째로 빠지면 본문이 프리뷰(~300자)로 잘려 품질 게이트에 걸린다.
        # 원인을 못 찾고 '기사 실패'만 반복되지 않도록 stderr로 분명히 알린다.
        _warn_no_login()
    if has_login_cookies(cookies):
        steps.append(
            ("playwright_auth", lambda: parse_with_playwright_stealth(url, cookies=cookies))
        )
        steps.append(
            ("curl_cffi_auth", lambda: parse_with_curl_cffi_rotated(url, cookies=cookies))
        )
        steps.append(
            (
                "sa_api_auth",
                lambda: parse_with_sa_api(url, cookies=cookies, reject_locked_preview=True),
            )
        )
    steps.append(("jina_reader", lambda: parse_with_jina_reader(url)))
    if settings.ALLOW_ANON_FETCH:
        steps.append(("sa_api", lambda: parse_with_sa_api(url)))
        steps.append(("playwright_stealth", lambda: parse_with_playwright_stealth(url)))
        steps.append(("curl_cffi", lambda: parse_with_curl_cffi_rotated(url)))

    attempts: List[Dict[str, Any]] = []
    for name, fn in steps:
        t0 = time.time()
        result = None
        error = None
        try:
            result = fn()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            result = {"method": name, "content": "", "error": error, "locked": True}
        elapsed_ms = int((time.time() - t0) * 1000)
        if result is None:
            result = {"method": name, "content": "", "locked": True}
        method = result.get("method") or name
        content = result.get("content") or ""
        error = result.get("error") or error
        locked = bool(result.get("locked") or result.get("rejected"))
        accepted = _acceptable_source(result)
        attempts.append(
            {
                "method": method,
                "chars": len(content),
                "locked": locked,
                "elapsed_ms": elapsed_ms,
                "error": error,
                "accepted": accepted,
            }
        )
        if not accepted:
            continue
        body = content
        if lead and (len(lead) < 40 or lead[-40:] not in body):
            result["content"] = f"{lead}\n\n{body}"
        result.setdefault("tickers", [])
        result["success"] = True
        result["error"] = None
        result["attempts"] = attempts
        return result

    max_chars = max((a["chars"] for a in attempts), default=0)
    return {
        "success": False,
        "title": "",
        "content": "",
        "method": None,
        "error": (
            f"All methods failed or preview-only (max {max_chars} chars, "
            f"min {AUTH_PREVIEW_LIMIT})"
        ),
        "attempts": attempts,
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
