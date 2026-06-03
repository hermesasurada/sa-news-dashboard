#!/bin/bash
# 휴지통 30일 경과분 영구삭제 — 요약(sa_publish)과 분리된 독립 정리 작업.
PY=/Users/yhandhs/Documents/sa-dashboard/venv/bin/python3
[ -x "$PY" ] || PY=python3
exec "$PY" /Users/yhandhs/Documents/sa-dashboard/scripts/sa_purge_deleted.py --days 30 "$@"
