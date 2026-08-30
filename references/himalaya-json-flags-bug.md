# himalaya Plain Text Flags Parsing

## Symptom
`himalaya envelope list --output json` returns `flags: ['Seen']` for ALL emails, regardless of actual read status.

## Root Cause
himalaya's JSON output has a bug where the flags field is populated incorrectly for all emails.

## Workaround
Use plain text output and check for `*` marker in the flags column (3rd field, between `|` delimiters):

```python
result = subprocess.run(['himalaya', 'envelope', 'list', '-s', '100'], capture_output=True, text=True)
lines = result.stdout.strip().split('\n')
for line in lines[2:]:  # Skip header + separator
    parts = line.split('|')
    flags = parts[2].strip()
    if '*' in flags:  # Has '*' = read
        ...
    else:  # Empty or no '*' = unread
        ...
```

## Notes
- Plain text output correctly shows `*` marker for read emails
- The flags column is the 3rd field (index 2) when split by `|`
- Unread emails have an empty flags column

## Related
- `scripts/extract_sa_urls.py` — uses plain text output for flag detection
- SA cron jobs depend on this script for unread detection
