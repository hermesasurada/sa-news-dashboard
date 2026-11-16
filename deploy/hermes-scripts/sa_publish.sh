#!/bin/bash
# Stage 2 publish — Claude CLI 기반 요약. dashboard venv python 필수.
PY=/Users/yhandhs/projects/sa-news/venv/bin/python3
[ -x "$PY" ] || PY=python3
# 원문 통로 기본값은 Grok Bot(SA_SOURCE_MODE=grok)이고 SA 로그인 수집은 기본 끔(SA_USE_LOGIN=0, 2026-10-11).
# 로그인 수집을 켜면(SA_USE_LOGIN=1) 세션 무효화는 sa_login_state가 감지해 익명 경로로 자동 폴백한다.

exec "$PY" /Users/yhandhs/projects/sa-news/scripts/sa_summarize_claude.py --batch 10 "$@"
