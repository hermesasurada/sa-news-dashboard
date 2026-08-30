# extract_card_info — Bug History & Fixes (2026-05-14)

## Root Cause: depth counting off-by-one

**Problem:** `depth = 0; pos = start + 1` 로 시작하면 첫 번째 `</div>`(card-header 닫힘)에서 depth=-1→0이 돼 카드 블록이 너무 일찍 종료됨.

**Fix:** `depth = 1; pos = start + len('<div class="card">')` 으로 시작. 이미 opening tag를 통과했으니 depth=1.

```python
# WRONG (was causing cards to return title='')
depth = 0
pos = start + 1

# CORRECT
depth = 1
pos = start + len('<div class="card">')
```

## Historical ticker class formats (all 4 must be supported)

| Format | Example | Era |
|---|---|---|
| `class="ticker-badge ticker-blue"` | 2026-05-14+ | New (current) |
| `class="ticker ticker-blue"` | 2026-05-12 | Old |
| `class="badge ticker-blue"` | 2026-05-12 | Old variant |
| `class="ticker" style="background:..."` | 2026-05-12 | Old inline |

Regex priority order: ticker-badge → ticker ticker-* → badge ticker-* → ticker[style]

## Ticker validation

After extracting raw text from span, validate before storing:
```python
if re.match(r'^[A-Z0-9\.\-]{1,10}$', raw) or re.match(r'^\d{6}$', raw):
    ticker = raw
elif re.search(r'[A-Z]{2,6}', raw):
    # Multi-ticker "SPY · DIA · QQQ" → take first
    first = re.search(r'[A-Z]{2,6}(?:\.[A-Z]{1,3})?', raw)
    ticker = first.group(0) if first else ''
else:
    ticker = ''  # skip labels like "실적 발표", "Seeking Alpha"
```

## Company span formats

```python
m = re.search(r'<span class="card-source">([^<]+)</span>', block)  # current
if not m: m = re.search(r'<span class="source">([^<]+)</span>', block)  # old
if not m: m = re.search(r'<span class="company">([^<]+)</span>', block)  # older
```

## Title formats

```python
m = re.search(r'<h[23][^>]*>(.*?)</h[23]>', block, re.DOTALL)  # h2 or h3
if not m: m = re.search(r'<div[^>]+class="card-title"[^>]*>(.*?)</div>', block, re.DOTALL)
if not m: m = re.search(r'<div[^>]+class="subject"[^>]*>(.*?)</div>', block, re.DOTALL)
```

## Result: 54/54 dashboard files parsed correctly after fixes (2026-05-14)
