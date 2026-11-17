# SA Email Base64 URL Structure

## URL Format
SA Breaking News emails contain click-tracker URLs with this structure:
```
https://email-st.seekingalpha.com/click/<campaign_id>/<base64_string>/<hash_signature>
```

Example:
```
https://email-st.seekingalpha.com/click/45800863.8318/aHR0cHM6Ly9zZWVraW5n.../621b9243556101320d5793d4Beb24067e
```

## b64 Extraction
The base64 string is the **second-to-last** path segment (index 5 when split by `/`).

```python
url = "https://email-st.seekingalpha.com/click/45800863.8318/aHR0cHM6Ly8.../621b9243556101320d5793d4Beb24067e"
parts = url.split('/')
b64 = parts[5]  # The base64 string
```

## Why Regex Fails
A naive regex like `(aHR0cHM6[A-Za-z0-9+/=]{100,})` captures the b64 PLUS the trailing hash because both contain valid base64 characters (`/`, `=`, alphanumeric). The hash is NOT part of the b64 string and causes decoding to fail.

## Decoding
After extraction, add padding as needed:
```python
import base64
for pad in range(4):
    try:
        decoded = base64.b64decode(b64 + '=' * pad)
        break
    except Exception:
        pass
```

The decoded text contains:
- `ref=https://seekingalpha.com/news/...` — the actual article URL
- `main_0_title` or `main_0_textlink` — indicates main article (priority)
- `rc_0_analysis`, `rc_1_news` — related content links (lower priority)

## Related
- `scripts/extract_sa_urls.py` — uses this extraction method
- `references/himalaya-json-flags-bug.md` — flags detection workaround
