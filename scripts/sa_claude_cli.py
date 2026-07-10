#!/usr/bin/env python3
"""SA news — Claude CLI 공용 유틸.

sa_summarize_claude.py 가 사용:
  - resolve_claude_bin(): 버전 pin 없이 최신 Claude CLI 바이너리 동적 탐지
  - call_claude(prompt, timeout): stream-json 호출 후 최종 텍스트 반환
  - extract_json(text): 응답에서 JSON 객체 추출

환경변수:
  CLAUDE_BIN / CLAUDE_CODE_BIN — 바이너리 경로 override
  CLAUDE_MODEL — 모델명 (기본 'opus' = 현재 claude-opus-4-8)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _version_key(path: Path) -> tuple[int, ...]:
    for part in path.parts:
        if re.fullmatch(r"\d+(?:\.\d+)+", part):
            return tuple(int(x) for x in part.split("."))
    return ()


def resolve_claude_bin() -> str:
    """Resolve Claude CLI path without pinning a versioned app bundle."""
    env_bin = os.environ.get("CLAUDE_BIN") or os.environ.get("CLAUDE_CODE_BIN")
    if env_bin:
        return str(Path(env_bin).expanduser())

    app_support = Path.home() / "Library/Application Support/Claude"
    candidates = [
        *app_support.glob("claude-code/*/claude.app/Contents/MacOS/claude"),
        *app_support.glob("claude-code-vm/*/claude"),
    ]
    candidates = [p for p in candidates if p.is_file()]
    if candidates:
        return str(max(candidates, key=lambda p: (_version_key(p), "claude.app" in str(p))))

    return "claude"


CLAUDE_BIN = resolve_claude_bin()
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "opus")


def resolve_grok_bin() -> str:
    """grok CLI 경로 — cron bare PATH 대비 절대경로 fallback."""
    env_bin = os.environ.get("GROK_BIN")
    if env_bin:
        return str(Path(env_bin).expanduser())
    return shutil.which("grok") or str(Path.home() / ".grok" / "bin" / "grok")


GROK_BIN = resolve_grok_bin()
GROK_MODEL = os.environ.get("GROK_MODEL", "")  # 빈값 = grok 기본 모델


def call_claude(prompt: str, timeout: int = 120) -> tuple[str | None, str | None]:
    """Claude CLI 호출 → (응답 텍스트, 실제 모델ID) 반환. 실패 시 (None, None).

    모델ID는 stream-json 이벤트의 model 필드(예: 'claude-opus-4-8')를 캡처 —
    'opus' 별칭이 아니라 실제 처리 모델 버전을 기록하기 위함.
    """
    try:
        proc = subprocess.Popen(
            [
                CLAUDE_BIN,
                "--output-format", "stream-json",
                "--verbose",
                "--model", CLAUDE_MODEL,
                "-p", prompt,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        result_text = None
        model_id = None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev_type = ev.get("type")
            # 모델ID 캡처 (system/assistant/result 이벤트에 포함)
            if not model_id:
                model_id = ev.get("model") or ev.get("message", {}).get("model")
            # result 이벤트 — 최종 응답 텍스트
            if ev_type == "result" and ev.get("subtype") == "success":
                result_text = ev.get("result", "")
            # assistant 이벤트 — result 없을 때 fallback
            elif ev_type == "assistant" and result_text is None:
                for blk in ev.get("message", {}).get("content", []):
                    if blk.get("type") == "text":
                        result_text = blk.get("text", "")

        proc.wait(timeout=timeout)
        if proc.returncode != 0:
            err = proc.stderr.read(300)
            print(f"     Claude CLI 오류 (rc={proc.returncode}): {err}", file=sys.stderr)
            return None, None
        text = (result_text or "").strip() or None
        return text, (model_id or CLAUDE_MODEL if text else None)

    except subprocess.TimeoutExpired:
        proc.kill()
        print("     Claude CLI 타임아웃", file=sys.stderr)
        return None, None
    except Exception as e:
        print(f"     Claude CLI 호출 실패: {e}", file=sys.stderr)
        return None, None


def extract_json(text: str) -> dict | None:
    """Claude 응답에서 JSON 객체 추출."""
    text = text.strip()
    # 마크다운 코드블럭 제거
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # 직접 파싱 시도
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # { ... } 블럭 추출
    m2 = re.search(r"\{[\s\S]*\}", text)
    if m2:
        try:
            return json.loads(m2.group())
        except json.JSONDecodeError:
            pass
    return None


_GROK_DEFAULT_MODEL = None


def _grok_default_model() -> str:
    """`grok models`의 'Default model: X' 를 파싱해 기본 모델명 반환(캐시). 실패 시 'grok'."""
    global _GROK_DEFAULT_MODEL
    if _GROK_DEFAULT_MODEL is not None:
        return _GROK_DEFAULT_MODEL
    model = "grok"
    try:
        proc = subprocess.run(
            [GROK_BIN, "models"],
            capture_output=True, text=True, encoding="utf-8",
            timeout=30, cwd=tempfile.gettempdir(),
        )
        m = re.search(r"Default model:\s*(\S+)", proc.stdout or "")
        if m:
            model = m.group(1)
    except Exception:
        pass
    _GROK_DEFAULT_MODEL = model
    return model


def call_grok(prompt: str, timeout: int = 120) -> tuple[str | None, str | None]:
    """Claude 실패 시 폴백 — grok CLI 헤드리스 호출 → (텍스트, 모델ID). 실패 시 (None, None).

    `grok -p <PROMPT> --output-format plain` 으로 응답 텍스트만 stdout 수신.
    응답 형식은 Claude와 동일(요약 JSON 텍스트) → 호출측에서 extract_json 재사용.
    모델ID는 GROK_MODEL(지정 시) 또는 grok 기본 모델(예: 'grok-4.5').
    """
    model = GROK_MODEL or _grok_default_model()
    try:
        cmd = [GROK_BIN, "-p", prompt, "--output-format", "plain"]
        if GROK_MODEL:
            cmd += ["-m", GROK_MODEL]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=tempfile.gettempdir(),  # 프로젝트 파일 스캔 방지 (순수 텍스트 생성)
        )
        if proc.returncode != 0:
            print(f"     Grok CLI 오류 (rc={proc.returncode}): {(proc.stderr or '')[:300]}", file=sys.stderr)
            return None, None
        text = (proc.stdout or "").strip() or None
        return text, (model if text else None)
    except subprocess.TimeoutExpired:
        print("     Grok CLI 타임아웃", file=sys.stderr)
        return None, None
    except Exception as e:
        print(f"     Grok CLI 호출 실패: {e}", file=sys.stderr)
        return None, None
