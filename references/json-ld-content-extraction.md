# JSON-LD Content Extraction for SA Articles

SA (Seeking Alpha) articles embed rich metadata in JSON-LD `<script type="application/ld+json">` tags. The `description` field often contains more specific information (numbers, tickers, forecasts) than the visible article body.

## Why This Matters

SA news articles are often short (3-5 paragraphs). The JSON-LD `description` can add critical context:
- Market forecasts with specific numbers (~35% CAGR)
- Ticker symbols (COHR, FN, LITE)
- Technology references (1.6T/800G, CPO)

## Extraction Pattern

```python
import re, json

json_ld_desc = ""
json_lds = re.findall(
    r'<script type="application/ld\+json">(.*?)</script>',
    html_content, re.DOTALL
)
for jld in json_lds:
    try:
        data = json.loads(jld)
        if isinstance(data, dict) and data.get("@type") == "NewsArticle":
            desc = data.get("description", "")
            if desc and len(desc) > 50:
                json_ld_desc = desc
                break
    except Exception:
        pass
```

## Integration with Article Body

Place JSON-LD description between title and body:
```
{title}

{json_ld_desc}

{body_text}
```

This ensures the LLM summarizer gets the richest possible source material.

## Caveats

- Not all SA pages have JSON-LD (older articles may lack it)
- The `description` field may be empty or very short — always check `len(desc) > 50`
- Multiple JSON-LD scripts may exist (e.g., NewsArticle + FAQPage) — iterate and pick the first valid NewsArticle
- JSON-LD is static HTML; it won't help with JS-rendered content
