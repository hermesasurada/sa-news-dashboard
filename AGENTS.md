# Ticker Coverage

- Supplement missing title subjects using the local portfolio ticker catalog and curated issuer aliases. Keep ADR/local equivalents deduplicated.
- Research attribution and explicit comparison references are not automatic subject candidates. Ambiguous short aliases must not be inferred.
- Keep symbol/name pairs together internally and retain the existing database/API string format for compatibility.
- Ticker backfills must preserve summaries, read status, publication state and article timestamps, and make a database backup first.

## Shared LLM catalog

- Model lists, display names and supported reasoning levels come from `~/projects/hermes-llm-log/llm_catalog.py` and `~/.hermes/data/llm_catalog.json`; manage them through the portal model-management page. Do not add independent UI option lists.
- Service selections, slot counts, routing and fallback order remain local. Preserve saved selections during catalog outages or model deactivation. New discoveries are candidates until manually enabled.
- Keep actual historical model IDs unchanged. Catalog readers must not depend on portal availability or trigger inference.

- **중앙 LLM 카탈로그(`hermes-llm-log/llm_catalog.py`)는 부가 정보다 — 못 불러와도 본업이 멈추면 안 된다**(2026-09-23 사용자 지시로 수정). import는 반드시 `try/except Exception`으로 감싸고 실패하면 `llm_catalog = None`으로 두고 사용처(`_grok_default_model`)가 None·예외를 처리한다. 카탈로그 경로는 `sys.path.append`로 **뒤에** 붙여 이 저장소 모듈을 가리지 않게 한다. 대체 모드의 선택지는 무엇이든 '포함'으로 답하므로 **모델 계열 판단에 선택지 소속(`in …_CHOICES`)을 쓰지 말고** `llm_catalog.resolve()`의 provider → 모델 ID 접두어 순으로 판단한다. 검증은 문법 오류가 있는 `llm_catalog.py`를 PYTHONPATH 앞에 끼워 재현한다(`tests/test_catalog_isolation.py`).

- 색상 모드(시스템·라이트·다크, 2026-09-24 사용자 지시): 공용 `static/hermes-theme.js`·`hermes-theme.css`는 sa·td·wm 세 저장소에서 **글자 단위로 같게** 유지한다. 선택값은 localStorage `hermes-theme`, 실제 색은 `<html data-theme="light|dark">`(JS가 시스템 설정까지 풀어 확정)로만 건다. 다크 보정은 `:root[data-theme="dark"]` 선택자로 앱 CSS의 다크 절에 둔다. 스크립트는 `<head>`에서 defer 없이 불러 첫 화면 깜빡임을 막는다.
