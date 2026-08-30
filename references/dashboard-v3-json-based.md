# SA Dashboard v3 — JSON-Based Architecture

## Overview (2026-05-13)

Complete redesign from v2 (3-panel fetch-based) to v3 (JSON-based, template rendering).

### Key Changes
- **No more fetch() for card content** — cards rendered directly from JSON data
- **JSON metadata** — `dashboard_meta.json` contains all dates, cards, URLs, extracted data
- **Template-based HTML** — `index.html` uses `DATES_JSON_PLACEHOLDER` replaced by Python script
- **No .container dependency** — cards rendered from JSON, no HTML parsing needed
- **Git sync without reset** — `git fetch && add -A && commit && push` (no `reset --hard`)

### File Structure
```
sa-dashboards/
├── index.html          ← Template (DATES_JSON_PLACEHOLDER)
├── dashboard_meta.json ← Generated JSON metadata
└── 2026-05-13/
    └── sa_dashboard_20260513_0100.html ← Source HTML (for reference)
```

### JSON Structure
```json
{
  "dates": {
    "2026-05-13": {
      "title": "2026-05-13",
      "total_articles": 23,
      "cards": [
        {
          "id": "sa_dashboard_20260513_0100",
          "time": "01:00",
          "file": "sa_dashboard_20260513_0100.html",
          "url": "https://hermesasurada.github.io/sa-dashboards/2026-05-13/sa_dashboard_20260513_0100.html",
          "cards_count": 2,
          "cards": [
            {"ticker": "BYDDF / NIO / XPEV", "company": "", "title": "...", "summary": "...", "url": "https://seekingalpha.com/news/..."}
          ]
        }
      ]
    }
  }
}
```

### Pitfalls Encountered
1. **META.dates vs META** — JSON passes `meta["dates"]` as `DATES_JSON_PLACEHOLDER`, so JS `META` IS the dates object. Use `META[date]` not `META.dates[date]`.
2. **Missing .container** — Source HTML files don't have `.container` wrapper. Cards are direct children of body.
3. **Git reset --hard** — Using `git reset --hard origin/main` after writing files reverts the new files. Use `git fetch` only, no reset.
4. **CORS/fetch failures** — Fetching HTML from GitHub Pages sometimes fails. Direct JSON rendering is more reliable.

### Script Changes (update_sa_dashboards.py)
- `generate_json()` — Scans dashboard HTML files, extracts card data, writes `dashboard_meta.json`
- `generate_index_html()` — Reads template, replaces `DATES_JSON_PLACEHOLDER`, writes `index.html`
- `git_sync()` — `fetch origin && add -A && commit && push` (NO reset)
