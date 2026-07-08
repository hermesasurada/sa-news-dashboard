#!/usr/bin/env python3
"""SA news — Claude CLI 공용 유틸.

sa_summarize_claude.py 가 사용:
  - resolve_claude_bin(): 버전 pin 없이 최신 Claude CLI 바이너리 동적 탐지
  - call_claude(prompt, timeout): stream-json 호출 후 최종 텍스트 반환
  - extract_json(text): 응답에서 JSON 객체 추출

환경변수:
  CLAUDE_BIN / CLAUDE_CODE_BIN — 바이너리 경로 override
  CLAUDE_MODEL — 모델명 (기본 'claude-opus-4-8')
"""
import json
import os
import re
import subprocess
import sys
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
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")


def call_claude(prompt: str, timeout: int = 120) -> str | None:
    """Claude CLI를 호출하고 최종 텍스트 응답을 반환. 실패 시 None."""
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
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev_type = ev.get("type")
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
            return None
        return (result_text or "").strip() or None

    except subprocess.TimeoutExpired:
        proc.kill()
        print("     Claude CLI 타임아웃", file=sys.stderr)
        return None
    except Exception as e:
        print(f"     Claude CLI 호출 실패: {e}", file=sys.stderr)
        return None


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
