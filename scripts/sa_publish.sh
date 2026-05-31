#!/bin/bash
# Stage 2: SA 기사 발행 — Claude CLI subprocess 로 한국어 요약 생성.
# Cron 진입점: ~/.hermes/scripts/sa_publish.sh 에서 이 파일을 호출.
#
# ⚠️ dashboard venv python 사용 필수: sa_article_parser.py 가 playwright/curl_cffi 를
#    import 하므로 이들이 설치된 venv 로 실행해야 함.
PY="$(dirname "$0")/../venv/bin/python3"
[ -x "$PY" ] || PY=python3
exec "$PY" "$(dirname "$0")/sa_summarize_claude.py" --batch 10 "$@"
