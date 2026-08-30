# SA Dashboard — 브라우저 도구 로컬호스트 접근 실패

## 증상 (2026-05-21)
`browser_navigate("http://localhost:8181/")` 호출 시 **타임아웃** 발생. 서버는 정상 작동 중 (PID 58365, 포트 8181 LISTEN, curl 200 OK).

## 원인
browser tool (headless Playwright)이 localhost URL 접근 시 타임아웃. Safari/Chrome 등 일반 브라우저에서는 정상 접근 가능.

## 해결
- **Safari/Chrome 직접 사용**: `http://localhost:8181` 주소창에 직접 입력
- **curl로 확인**: `curl -s http://localhost:8181/api/articles?limit=3`
- **Tailscale 외부 접근**: `http://<mac-mini-tailscale-ip>:8181` (browser tool에서 가능할 수 있음)

## 관련 증상
- `uvicorn.err` 파일이 1M+ 라인 (~80MB)로 팽창 — uvloop permission error 반복. 서버는 정상 작동 중이지만 로그 파일 관리 필요.
  - 해결: `truncate -s 0 ~/projects/sa-news/uvicorn.err` 또는 `> ~/projects/sa-news/uvicorn.err`
