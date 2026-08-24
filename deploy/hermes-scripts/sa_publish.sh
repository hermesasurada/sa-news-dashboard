#!/bin/bash
# Stage 2 publish — Claude CLI 기반 요약. dashboard venv python 필수.
PY=/Users/yhandhs/projects/sa-dashboard/venv/bin/python3
[ -x "$PY" ] || PY=python3
# ── SA 로그인 세션 무효(403) 상태 — 재로그인 전까지 익명 API 방식으로 운영 ──
#   재로그인(scripts/sa_refresh_login.py) 후에는 아래 3줄을 지우면
#   기본값(로그인 사용·본문 700자 기준)으로 돌아간다.
export SA_USE_LOGIN=0
export SA_ALLOW_ANON_FETCH=1
export SA_SOURCE_MIN_CHARS=200

exec "$PY" /Users/yhandhs/projects/sa-dashboard/scripts/sa_summarize_claude.py --batch 10 "$@"
