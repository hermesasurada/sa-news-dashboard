"""요약 모델 설정 — 대시보드 설정(톱니) 팝업이 저장하고 요약 파이프라인이 읽는다.

wm의 요약 모델 설정을 옮겼다(2026-09-26 사용자 지시). 모델 목록은 다른 서비스처럼
공용 LLM 카탈로그(hermes-llm-log/llm_catalog)의 Claude·GPT(Codex)·Grok 모델이다.
순번은 '순차 폴백' — 1순위가 요약하고, 실패하면 다음 순위가 받는다('사용 안 함'
칸은 건너뜀). 기본값은 Grok 4.7 한 칸. 저장은 sa_news.db의 app_settings
('summary_config'). 어떤 이유로든 읽지 못하면 기본값으로 요약을 계속한다.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

# Shared metadata; service execution policy remains local.
import sys as _catalog_sys
from pathlib import Path as _CatalogPath
_CATALOG_DIR = str(_CatalogPath.home() / "projects/hermes-llm-log")
if _CATALOG_DIR not in _catalog_sys.path:
    _catalog_sys.path.append(_CATALOG_DIR)
try:
    import llm_catalog
except Exception:  # noqa: BLE001 — 카탈로그는 부가 정보, 없어도 설정은 동작한다
    llm_catalog = None

import db

SETTINGS_KEY = "summary_config"
PROVIDERS = ("claude", "codex", "grok")
MODEL_KEYS = {"claude": "claude_model", "codex": "codex_model", "grok": "grok_model"}
DEFAULT_CONFIG = {
    "providers": ["grok"],
    "claude_model": "claude-opus-5-5", "codex_model": "gpt-6-sol", "grok_model": "grok-4.7",
    "reasoning": {"claude": "default", "codex": "default", "grok": "default"},
}
FALLBACK_LEVELS = ("default", "low", "medium", "high")
# 카탈로그를 못 읽을 때만 쓰는 최소 목록(설정 화면이 비지 않게)
_FALLBACK_MODELS = {"claude": [("claude-opus-5-5", "Opus 5.5")], "codex": [("gpt-6-sol", "GPT 6 Sol")],
                    "grok": [("grok-4.7", "Grok 4.7")]}


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)""")


def model_options(config: dict | None = None) -> list[dict]:
    """설정 팝업의 모델 목록 — 카탈로그에서 켜진 모델 + 지금 저장된 모델(비활성이어도 보존)."""
    cfg = config or DEFAULT_CONFIG
    out = []
    for provider in PROVIDERS:
        current = cfg.get(MODEL_KEYS[provider])
        items = None
        if llm_catalog:
            try:
                items = llm_catalog.options(provider, selected=[current] if current else [])
            except Exception:
                items = None
        if items is None:
            items = [{"value": v, "label": label, "provider": provider,
                      "reasoning": list(FALLBACK_LEVELS), "enabled": True}
                     for v, label in _FALLBACK_MODELS[provider]]
            # 카탈로그 장애 중에도 지금 저장된 모델은 목록에 남긴다 — 빠지면 화면이 실제 실행
            # 모델과 다른 모델을 보여 준다(Astra 검토, 2026-09-26).
            if current and all(o["value"] != current for o in items):
                items.insert(0, {"value": current, "label": current, "provider": provider,
                                 "reasoning": list(FALLBACK_LEVELS), "enabled": True})
        out.extend(dict(o, provider=provider) for o in items)
    return out


def reasoning_options() -> list[dict]:
    if llm_catalog:
        try:
            return llm_catalog.reasoning_options()
        except Exception:
            pass
    names = {"default": "모델 기본값", "low": "낮음", "medium": "보통", "high": "높음"}
    return [{"value": v, "label": names[v]} for v in FALLBACK_LEVELS]


def _levels(provider: str, model: str, config: dict | None = None) -> list[str]:
    hit = next((o for o in model_options(config) if o["provider"] == provider and o["value"] == model), None)
    return list(hit["reasoning"]) if hit else list(FALLBACK_LEVELS)


def normalize(raw) -> dict:
    """저장값을 형식에 맞춘다(모르는 칸은 기본값). 카탈로그에서 빠진 기존 모델은 보존한다."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if not isinstance(raw, dict):
        return cfg
    providers = [p for p in raw.get("providers") or [] if p in PROVIDERS]
    cfg["providers"] = list(dict.fromkeys(providers)) or cfg["providers"]
    for provider, key in MODEL_KEYS.items():
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            cfg[key] = value.strip()
    reasoning = raw.get("reasoning") if isinstance(raw.get("reasoning"), dict) else {}
    for provider in PROVIDERS:
        effort = str(reasoning.get(provider) or "default")
        cfg["reasoning"][provider] = effort
    return cfg


def validate(raw, current: dict | None = None) -> str | None:
    """POST 본문 검사 — 문제가 있으면 사유. 이미 저장돼 있던 값은 카탈로그에서 빠져도 통과."""
    if not isinstance(raw, dict):
        return "설정 형식이 잘못됐습니다"
    providers = raw.get("providers")
    if not isinstance(providers, list) or not providers:
        return "요약 모델을 하나 이상 켜 두어야 합니다"
    if any(p not in PROVIDERS for p in providers) or len(set(providers)) != len(providers):
        return "요약 순번이 잘못됐습니다"
    current = current or {}
    for provider in PROVIDERS:
        model = raw.get(MODEL_KEYS[provider])
        effort = str((raw.get("reasoning") or {}).get(provider) or "default")
        kept = (model == current.get(MODEL_KEYS[provider])
                and effort == (current.get("reasoning") or {}).get(provider))
        if kept:
            continue
        option = next((o for o in model_options(current) if o["provider"] == provider and o["value"] == model), None)
        if not option or not option.get("enabled", True):
            return f"선택할 수 없는 모델입니다: {model}"
        if effort not in option["reasoning"]:
            return f"{option['label']}는 추론 수준 {effort}를 지원하지 않습니다"
    return None


def load() -> dict:
    """저장된 설정. SA_SUMMARY_CONFIG_IGNORE_DB=1(테스트)이거나 못 읽으면 기본값."""
    if os.environ.get("SA_SUMMARY_CONFIG_IGNORE_DB"):
        return normalize(None)
    try:
        with db.get_conn() as conn:
            _ensure(conn)
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (SETTINGS_KEY,)).fetchone()
        return normalize(json.loads(row[0]) if row else None)
    except Exception:
        return normalize(None)


def save(raw) -> dict:
    cfg = normalize(raw)
    with db.get_conn() as conn:
        _ensure(conn)
        conn.execute(
            """INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (SETTINGS_KEY, json.dumps(cfg, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.commit()
    return cfg
