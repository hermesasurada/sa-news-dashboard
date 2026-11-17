# SA Dashboard v2 — Navigation Structure

## Root index.html (3-Panel Layout)
Three-column flex layout, fetch-based content rendering (no iframe):

```
┌─────────────┬──────────────┬──────────────────────────────┐
│ Date        │ Card List    │ Content Area                 │
│ Sidebar     │ Sidebar      │ (inline, fetch + DOMParser)  │
│             │              │                              │
│ 2026-05-13  │ 00:00 · 4KB  │ [Article cards rendered]     │
│   12개      │ 00:31 · 8KB  │                              │
│             │ 01:00 · 8KB  │ ┌────────────────────────┐   │
│ 2026-05-12  │ 01:32 · 8KB  │ │ TSLA | Tesla           │   │
│   24개      │ ...          │ │ Summary...             │   │
│             │              │ │ Details...             │   │
│ 2026-05-11  │              │ │ Tags: [긍정][AI]       │   │
│   2개       │              │ └────────────────────────┘   │
│             │              │                              │
└─────────────┴──────────────┴──────────────────────────────┘
```

### Interaction Flow
1. **Click date** → middle sidebar updates with that date's cards
2. **Click card** → right area fetches HTML, parses with DOMParser, renders inline
3. **Auto-select** first card on date load

### Data Source
- `DATE_DATA` JS object embedded in HTML: `{"2026-05-13":[{file, time, cards, size}, ...]}`
- ⚠️ (2026-05-31) **GitHub Pages 비활성화됨** — `https://hermesasurada.github.io/sa-dashboards/`는 더 이상 공개 서빙되지 않음. 대시보드 HTML은 로컬 `~/.hermes/reports`(repo: hermesasurada/sa-dashboards)에만 존재. 수집/요약 파이프라인(sa-collect/sa-publish)은 정상. 공개 게시가 다시 필요하면 Pages 재활성화 필요.
- Fetch → DOMParser → extract `.card` elements → render inline

## Per-Date index.html
Tile grid layout inside `YYYY-MM-DD/index.html`:
- Each tile links to individual dashboard HTML
- Header: "SA Dashboard - YYYY-MM-DD"
- Link: "← 전체 목록으로" back to root index.html

## Generation
`update_sa_dashboards.py` generates both:
1. Per-date `index.html` files
2. Root `index.html` with `DATE_DATA` + inline JS
