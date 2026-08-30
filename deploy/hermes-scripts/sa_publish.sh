#!/bin/bash
# Stage 2 publish — Claude CLI 기반 요약. dashboard venv python 필수.
PY=/Users/yhandhs/projects/sa-news/venv/bin/python3
[ -x "$PY" ] || PY=python3
# 로그인 쿠키 세션을 기본으로 쓴다. 서버가 세션을 무효화하면
# sa_login_state가 감지해 익명 경로로 자동 폴백하고, 재로그인 후에는
# 자동으로 복귀한다(수동 환경변수 조정 불필요).

exec "$PY" /Users/yhandhs/projects/sa-news/scripts/sa_summarize_claude.py --batch 10 "$@"
