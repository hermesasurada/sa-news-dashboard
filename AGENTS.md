# Ticker Coverage

- Supplement missing title subjects using the local portfolio ticker catalog and curated issuer aliases. Keep ADR/local equivalents deduplicated.
- Research attribution and explicit comparison references are not automatic subject candidates. Ambiguous short aliases must not be inferred.
- Keep symbol/name pairs together internally and retain the existing database/API string format for compatibility.
- Ticker backfills must preserve summaries, read status, publication state and article timestamps, and make a database backup first.

## Shared LLM catalog

- Model lists, display names and supported reasoning levels come from `~/projects/hermes-llm-log/llm_catalog.py` and `~/.hermes/data/llm_catalog.json`; manage them through the portal model-management page. Do not add independent UI option lists.
- Service selections, slot counts, routing and fallback order remain local. Preserve saved selections during catalog outages or model deactivation. New discoveries are candidates until manually enabled.
- Keep actual historical model IDs unchanged. Catalog readers must not depend on portal availability or trigger inference.
