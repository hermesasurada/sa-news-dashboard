"""요약 모델 설정 — 대시보드 설정(톱니) 팝업이 저장하고 요약 파이프라인이 읽는다.

wm의 요약 모델 설정을 옮겼다(2026-09-26 사용자 지시). 처음에는 Grok 4.7 한 칸만
고를 수 있다 — 순번에 없는 모델로는 폴백하지 않는다(예전의 Claude 폴백도 없음).
저장은 sa_news.db의 app_settings('summary_config'). 어떤 이유로든 읽지 못하면
기본값으로 요약을 계속한다.
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
# 고를 수 있는 모델 — 사용자 지시로 당분간 Grok 4.7 하나(필요하면 여기에 더한다).
MODEL_CHOICES = {"grok": ("grok-4.7",)}
FALLBACK_LEVELS = ("default", "low", "medium", "high")
DEFAULT_CONFIG = {"providers": ["grok"], "grok_model": "grok-4.7", "reasoning": {"grok": "default"}}
_LABELS = {"grok-4.7": "Grok 4.7"}


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)""")


def model_options() -> list[dict]:
    """설정 팝업의 모델 목록 — {provider, value, label, reasoning}."""
    out = []
    for provider, models in MODEL_CHOICES.items():
        for model in models:
            entry = llm_catalog.resolve(model, provider) if llm_catalog else None
            out.append({
                "provider": provider, "value": model,
                "label": (entry or {}).get("label") or _LABELS.get(model, model),
                "reasoning": list((entry or {}).get("reasoning") or FALLBACK_LEVELS),
            })
    return out


def reasoning_options() -> list[dict]:
    if llm_catalog:
        try:
            return llm_catalog.reasoning_options()
        except Exception:
            pass
    names = {"default": "모델 기본값", "low": "낮음", "medium": "보통", "high": "높음"}
    return [{"value": v, "label": names[v]} for v in FALLBACK_LEVELS]


def _levels(model: str) -> list[str]:
    hit = next((o for o in model_options() if o["value"] == model), None)
    return hit["reasoning"] if hit else list(FALLBACK_LEVELS)


def normalize(raw) -> dict:
    """저장값을 현재 선택지 안으로 맞춘다(모르는 값은 기본값으로)."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if not isinstance(raw, dict):
        return cfg
    providers = [p for p in raw.get("providers") or [] if p in MODEL_CHOICES]
    cfg["providers"] = list(dict.fromkeys(providers)) or cfg["providers"]
    if raw.get("grok_model") in MODEL_CHOICES["grok"]:
        cfg["grok_model"] = raw["grok_model"]
    effort = str((raw.get("reasoning") or {}).get("grok") or "default")
    cfg["reasoning"]["grok"] = effort if effort in _levels(cfg["grok_model"]) else "default"
    return cfg


def validate(raw) -> str | None:
    """POST 본문 검사 — 문제가 있으면 사유."""
    if not isinstance(raw, dict):
        return "설정 형식이 잘못됐습니다"
    providers = raw.get("providers")
    if not isinstance(providers, list) or not providers:
        return "요약 모델을 하나 이상 켜 두어야 합니다"
    if any(p not in MODEL_CHOICES for p in providers):
        return "선택할 수 없는 모델이 있습니다"
    if raw.get("grok_model") not in MODEL_CHOICES["grok"]:
        return "선택할 수 없는 Grok 모델입니다"
    effort = str((raw.get("reasoning") or {}).get("grok") or "default")
    if effort not in _levels(raw["grok_model"]):
        return f"{raw['grok_model']}는 추론 수준 {effort}를 지원하지 않습니다"
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
