# SA Dashboard FastAPI + SQLite 웹앱 구조

## 파일 구조
```
~/projects/sa-news/
  app.py          # FastAPI 앱 (REST API)
  db.py           # SQLite 연결/쿼리/FTS5
  migrate.py      # 기존 HTML → DB 마이그레이션
  sa_news.db      # SQLite DB 파일
  static/
    index.html    # 카드 UI + 검색/필터/페이지네이션
```

## DB 스키마 (db.py)
```sql
CREATE TABLE articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    ticker_color    TEXT NOT NULL DEFAULT 'blue',
    company_name    TEXT NOT NULL,
    headline        TEXT NOT NULL,
    summary_core    TEXT NOT NULL,
    summary_details TEXT NOT NULL,   -- JSON array
    tag             TEXT NOT NULL,
    tag_color       TEXT NOT NULL DEFAULT 'blue',
    article_url     TEXT NOT NULL,
    email_time_et   TEXT,
    email_id        TEXT UNIQUE,     -- 중복 방지
    created_at      TEXT NOT NULL    -- ISO8601 KST
);
CREATE VIRTUAL TABLE articles_fts USING fts5(...);  -- 전문검색
```

## REST API 엔드포인트 (app.py)
- `GET /` — index.html
- `GET /api/articles?q=&ticker=&tag=&date_from=&date_to=&limit=50&offset=0`
- `GET /api/filters` — 티커/태그 목록 (검색 UI 드롭다운용)
- `GET /api/article/{id}` — 단건 조회

## 서버 실행
```bash
cd ~/projects/sa-news
/Users/yhandhs/Library/Python/3.9/bin/uvicorn app:app --host 0.0.0.0 --port 8181 --reload
```

## launchd 자동 기동
`~/Library/LaunchAgents/com.user.sa-dashboard.plist`
```bash
launchctl load ~/Library/LaunchAgents/com.user.sa-dashboard.plist
launchctl unload ~/Library/LaunchAgents/com.user.sa-dashboard.plist  # 중지
```

## 접근 URL
- 로컬: `http://localhost:8181`
- 외부(Tailscale): `http://<mac-mini-tailscale-ip>:8181`

## 마이그레이션 (migrate.py)
기존 HTML 파일 → DB 일괄 삽입:
```bash
cd ~/projects/sa-news && python3 migrate.py
```
- `~/Documents/reports/**/sa_dashboard_*.html` 전체 스캔
- 파일명에서 KST 시각 파싱 → `created_at`으로 사용
- `email_id = migrate:<filename>:<index>` 로 중복 방지
- 2026-05-16 기준: 76파일 → 158건 삽입

## Python 3.9 호환 주의
- `int | None` 타입힌트 사용 불가 → 그냥 생략하거나 `Optional[int]` 사용
- `list[str]` → 그냥 `list` 또는 생략
- `executescript()` 사용 — `;` split 방식은 VIRTUAL TABLE 구문에서 오류 발생

## 포트 충돌
- 8080: 다른 서비스가 점유 (`/opt/homebrew/var`에서 실행 중인 Python)
- 8000: `python -m http.server 8000` (~/Documents/reports/ 서빙)
- **8181: SA Dashboard FastAPI 전용**
