# Ticker Coverage

- Supplement missing title subjects using the local portfolio ticker catalog and curated issuer aliases. Keep ADR/local equivalents deduplicated.
- Research attribution and explicit comparison references are not automatic subject candidates. Ambiguous short aliases must not be inferred.
- Keep symbol/name pairs together internally and retain the existing database/API string format for compatibility.
- Ticker backfills must preserve summaries, read status, publication state and article timestamps, and make a database backup first.
