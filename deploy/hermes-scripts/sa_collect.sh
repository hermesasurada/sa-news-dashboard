#!/bin/bash
# Stage 1 collect — himalaya 미읽음 SA 메일 → pending 행. dashboard venv python으로 통일.
# PATH 보강: hermes Desktop 앱이 cron 틱을 잡으면 launchd 기본 PATH(/usr/bin:...)라
# /opt/homebrew/bin(himalaya)이 빠짐 → 어느 스케줄러가 돌려도 동작하도록 명시.
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
PY=/Users/yhandhs/Documents/sa-dashboard/venv/bin/python3
[ -x "$PY" ] || PY=python3
exec "$PY" /Users/yhandhs/Documents/sa-dashboard/scripts/sa_collect.py "$@"
