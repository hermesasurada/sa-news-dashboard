#!/bin/bash
# Stage 1: SA 이메일 수집 — LLM 미사용, SA 페이지 미접속.
# Cron 진입점: ~/.hermes/scripts/sa_collect.sh 에서 이 파일을 호출.
exec python3 "$(dirname "$0")/sa_collect.py" "$@"
