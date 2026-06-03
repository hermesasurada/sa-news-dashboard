#!/bin/bash
# Stage 1 collect — himalaya 미읽음 SA 메일 → pending 행. dashboard venv python으로 통일.
PY=/Users/yhandhs/Documents/sa-dashboard/venv/bin/python3
[ -x "$PY" ] || PY=python3
exec "$PY" /Users/yhandhs/Documents/sa-dashboard/scripts/sa_collect.py "$@"
