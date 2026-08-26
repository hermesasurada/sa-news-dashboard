"""SA 로그인 세션 상태 — 무효를 감지하면 익명 경로로 자동 폴백한다.

SA는 쿠키 만료일이 남아 있어도 서버에서 세션을 무효화한다(2026-08 실제 사례).
이때 쿠키 파일은 멀쩡해 보이므로 `has_login_cookies()`로는 감지되지 않고,
기사마다 인증 3단계를 헛되이 시도한 뒤 프리뷰(~300자)만 얻어 품질 게이트에
걸린다. 결과적으로 발행이 통째로 멈춘다.

그래서 '실제로 인증이 먹히는가'를 결과로 판정해 상태 파일에 남긴다.
  - 인증 경로가 연속 FAIL_THRESHOLD회 프리뷰만 반환 → degraded 진입
  - degraded 동안 인증 경로를 건너뛰고(기사당 ~11초 절약) 익명 경로를 허용,
    본문 길이 기준도 완화한다
  - REPROBE_MINUTES마다 1회 인증을 다시 시도해, 재로그인이 끝났으면
    자동으로 정상 복귀한다

프로세스는 배치마다 새로 뜨므로 메모리 카운터는 쓸 수 없다. 파일에 남긴다.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict

import settings


def _default() -> Dict[str, Any]:
    return {
        "degraded_since": None,
        "consecutive_failures": 0,
        "last_probe": 0.0,
        "last_success": None,
    }


def load_state() -> Dict[str, Any]:
    """상태 파일을 읽는다. 없거나 깨졌으면 기본값(정상)으로 본다."""
    try:
        data = json.loads(settings.LOGIN_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default()
        base = _default()
        base.update(data)
        return base
    except Exception:
        return _default()


def _save(state: Dict[str, Any]) -> None:
    """원자적 교체. 상태 저장 실패가 파이프라인을 멈추게 해서는 안 된다."""
    path = settings.LOGIN_STATE_PATH
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass


def is_degraded() -> bool:
    """세션 무효로 판정돼 익명 폴백 중인가."""
    if not settings.USE_LOGIN_SESSION:
        return False
    return bool(load_state().get("degraded_since"))


def should_probe() -> bool:
    """degraded 중이지만 재로그인 여부를 확인할 때가 됐는가."""
    state = load_state()
    if not state.get("degraded_since"):
        return False
    last = float(state.get("last_probe") or 0)
    return (time.time() - last) >= settings.LOGIN_REPROBE_MINUTES * 60


def record_auth_result(ok: bool, *, probed: bool = False) -> None:
    """인증 경로가 실제로 본문을 얻었는지 기록하고 degraded를 전환한다.

    ok=True  : 인증이 살아 있다 → 카운터 리셋, degraded 해제
    ok=False : 프리뷰만 얻었다 → 카운터 증가, 임계치 넘으면 degraded 진입
    probed   : degraded 중 재프로브였는가(성공/실패 무관하게 시각을 남긴다)
    """
    state = load_state()
    now = time.time()
    if probed:
        state["last_probe"] = now

    if ok:
        recovered = bool(state.get("degraded_since"))
        state["consecutive_failures"] = 0
        state["degraded_since"] = None
        state["last_success"] = now
        _save(state)
        if recovered:
            print(
                "     ✅ SA 로그인 세션 복구 — 인증 경로로 되돌립니다.",
                flush=True,
            )
        return

    state["consecutive_failures"] = int(state.get("consecutive_failures") or 0) + 1
    entering = (
        not state.get("degraded_since")
        and state["consecutive_failures"] >= settings.LOGIN_FAIL_THRESHOLD
    )
    if entering:
        state["degraded_since"] = now
        state["last_probe"] = now
    _save(state)

    if entering:
        # cron stdout은 텔레그램으로 전달된다. 전환 시점에만 1회 알린다.
        print(
            f"     ⚠️ SA 로그인 세션 무효 — 인증이 {state['consecutive_failures']}회 연속 "
            f"프리뷰만 반환했습니다. 익명 경로로 자동 전환합니다(본문 축약). "
            f"복구: python3 scripts/sa_refresh_login.py "
            f"({settings.LOGIN_REPROBE_MINUTES}분마다 자동 재확인)",
            flush=True,
        )
        print(
            "     ⚠️ SA 로그인 세션 무효 → 익명 폴백 진입",
            file=sys.stderr,
            flush=True,
        )


def effective_min_chars() -> int:
    """본문 길이 기준. 익명 폴백 중에는 SA가 프리뷰만 주므로 완화한다."""
    if is_degraded() or not settings.USE_LOGIN_SESSION:
        return settings.DEGRADED_MIN_CHARS
    return settings.SOURCE_MIN_CHARS


def enforce_locked_gate() -> bool:
    """'잠금 본문 거부' 규칙을 적용할 상황인가.

    익명(또는 폴백) 상태에서는 받는 본문이 전부 잠금 프리뷰라, 잠금으로 거르면
    아무것도 발행할 수 없다."""
    return settings.USE_LOGIN_SESSION and not is_degraded()
