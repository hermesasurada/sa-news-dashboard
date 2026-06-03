#!/bin/bash
# Stage 2 publish — Claude CLI 기반 요약. dashboard venv python 필수.
PY=/Users/yhandhs/Documents/sa-dashboard/venv/bin/python3
[ -x "$PY" ] || PY=python3
exec "$PY" /Users/yhandhs/Documents/sa-dashboard/scripts/sa_summarize_claude.py --batch 10 "$@"
