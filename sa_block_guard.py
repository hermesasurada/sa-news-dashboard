"""SA 봇 차단(PerimeterX 'Press & Hold' 확인 화면) 쿨다운 — 2026-10-10 사용자 지시: 최대한 차단되지 않게.

차단 화면을 한 번이라도 받으면 그 즉시 SA 요청을 모두 멈추고, 쿨다운이 끝날 때까지 어떤 경로로도
SA에 접속하지 않는다. 차단 중에 기사마다 폴백 경로(브라우저·curl 3종·API)를 연달아 두드리면
차단이 길어지기만 한다(2026-10-10: 확인 요청 몇 번에 403이 걸렸다). 확인 화면은 우회하지 않는다.

  - 쿨다운: 차단마다 BLOCK_COOLDOWN_MINUTES로 고정(연속 차단 두 배 늘리기는 2026-10-10 사용자 지시로 없앰)
  - 연속 횟수는 알림·기록용으로만 센다(본문을 정상으로 받으면 0)
  - 프로세스는 배치마다 새로 뜨므로 상태는 파일에 남긴다(로그인 상태 파일 옆)
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict

import settings

_MARKERS = ("px-captcha", "captcha.px-cloud", "Access to this page has been denied",
            "Press & Hold to confirm you are", "PXxgCxM9By")


class SABlocked(Exception):
    """SA가 봇 확인 화면을 돌려줬다 — 이번 배치의 SA 요청을 모두 멈춘다."""


def is_block_page(status: int | None, text: str | None) -> bool:
    """403/429 + PerimeterX 확인 화면이면 True."""
    if status not in (403, 429):
        return False
    head = (text or "")[:20000]
    return status == 429 or any(m in head for m in _MARKERS)


def _default() -> Dict[str, Any]:
    return {"blocked_until": 0.0, "consecutive_blocks": 0, "last_block": None}


def load_state() -> Dict[str, Any]:
    try:
        data = json.loads(settings.BLOCK_STATE_PATH.read_text(encoding="utf-8"))
        base = _default()
        if isinstance(data, dict):
            base.update(data)
        return base
    except Exception:
        return _default()


def _save(state: Dict[str, Any]) -> None:
    path = settings.BLOCK_STATE_PATH
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass


def remaining_seconds() -> int:
    """쿨다운이 남았으면 남은 초, 아니면 0."""
    return max(0, int(float(load_state().get("blocked_until") or 0) - time.time()))


def record_block(where: str = "") -> int:
    """차단을 기록하고 쿨다운(분)을 돌려준다."""
    state = load_state()
    n = int(state.get("consecutive_blocks") or 0) + 1
    minutes = settings.BLOCK_COOLDOWN_MINUTES
    state.update(consecutive_blocks=n, blocked_until=time.time() + minutes * 60, last_block=time.time())
    _save(state)
    msg = (f"     ⛔ SA 봇 확인 화면 감지({where or 'SA'}) — {minutes}분 동안 SA 요청을 멈춥니다"
           f"(연속 {n}회). 기사는 대기열에 그대로 남습니다.")
    print(msg, flush=True)
    print(msg, file=sys.stderr, flush=True)
    return minutes


def record_ok() -> None:
    state = load_state()
    if state.get("consecutive_blocks"):
        state["consecutive_blocks"] = 0
        _save(state)


def check(text: str | None, status: int | None, where: str) -> None:
    """응답이 차단 화면이면 기록하고 SABlocked를 올린다."""
    if is_block_page(status, text):
        record_block(where)
        raise SABlocked(where)
