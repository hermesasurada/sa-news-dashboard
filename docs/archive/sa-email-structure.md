# SA Email Structure Reference

## SA Breaking News Email Formats

### Daily Digest (e.g., email 18)
- **Subject**: `TICKER: Headline`
- **Body**: Contains main article link + "You may also like" related links
- **Main link pattern**: `main_0_title` in decoded URL
- **Related links**: `rc_0_analysis`, `rc_1_news`, `rc_2_news`

### Individual Breaking News (e.g., email 13 TSLA)
- **Subject**: `TICKER: AM Markets Need to Know: Chip stocks, Fed hikes, and more`
- **Body**: Same structure as digest — main link + related links
- **Main link pattern**: `main_0_title`

### Emails Without `main_0_title` (e.g., email 14 Alibaba, email 15 Walmart)
- **Subject**: `TICKER: Headline`
- **Body**: Contains article links but NO `main_0_title` pattern
- **First URL per email** is the main article
- All URLs have no position parameter (just `ref=URL`)

### Newsletter-Style Emails (SKIP — No Main Article)
- **Subject**: `TICKER: Headline` (looks like normal breaking news)
- **Body**: Contains ONLY related content links (`rc_1_news`, `rc_2_news`, `seeking_alpha`)
- **NO main article link** at all
- **Action**: Skip entirely — these are digest/roundup emails with no single main article
- Example: Email 20 (AMZN) had only `rc_1_news` and `rc_2_news` links

## Base64 Click-Tracker Structure

### Format
```
https://email-st.seekingalpha.com/click/<campaign_id>/<base64url>/...
```

### Decoded Content
```
https://seekingalpha.com/account/email-auth?sailethru_auth_param=...&ref=ACTUAL_URL
```

The `ref` parameter contains the actual article URL.

### Base64 Padding Issue
SA base64 strings often lack proper padding. Python fix:
```python
missing = len(b64) % 4
if missing: b64 += '=' * (4 - missing)
```

### Regex to Find Base64 Strings
```
aHR0cHM6[A-Za-z0-9+/=]{100,}
```
(All SA base64 strings start with `aHR0cHM6` = `https:`)

## himalaya Flag Mismatch

### Problem
himalaya shows `*` in FLAGS column for `\Seen` (read) flag. But this may not match Gmail's UI:
- Email marked `\Seen` by himalaya may still appear unread in Gmail
- Emails processed by cron may be marked `\Seen` without user actually reading them

### Workaround
Always verify by reading email content (`himalaya message read <ID>`), don't rely solely on flag state.

## Common SA Article URL Patterns

| Pattern | Description |
|---------|-------------|
| `seekingalpha.com/news/<id>-<slug>` | Breaking news article |
| `seekingalpha.com/article/<id>-<slug>` | Full analysis article |
| `seekingalpha.com/symbol/<TICKER>` | Ticker page |
| `seekingalpha.com/market-news/trending` | Trending news page |