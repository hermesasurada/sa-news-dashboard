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
- 대시보드 상단은 2줄이다(2026-09-24 사용자 지시): 1줄 = 타이틀 + [글꼴][색상 모드][휴지통], 2줄 = 검색어 + 검색·정렬기준·정렬방향·초기화·미읽음. 티커 선택 버튼·모달은 삭제했다(검색어로 티커도 찾는다, API의 ticker 파라미터는 남김). 모바일(≤680px)은 버튼 아이콘만.
- 상단(타이틀+검색조건)은 스크롤해도 고정된다(2026-09-24 사용자 지시): 두 줄을 `.hermes-gnb`로 감싸고 스타일·밑줄 처리는 공용 hermes-theme.css/js가 맡는다. 붙어 있을 때 밑줄 아래 10px 여백. 조상에 `overflow-x: hidden`을 두면 sticky가 깨지므로 `clip`을 쓴다. 고정 영역 z-index(40)는 모달보다 낮게 유지.
- 요약 모델 설정(2026-09-26 사용자 지시, wm 설정 팝업 이식): 헤더 톱니 → 공용 `static/model-selector.{js,css}`(wm·yt와 글자 단위로 같게 유지) 계열 모드. 저장은 `sa_news.db` `app_settings.summary_config`, 규칙은 `summary_config.py`. 모델 목록은 다른 서비스처럼 **공용 LLM 카탈로그**(Claude·GPT(Codex)·Grok, 켜진 모델 + 저장된 기존 모델 보존). 순번은 **순차 폴백**(1순위 → 실패 시 다음, '사용 안 함' 건너뜀, 기본은 Grok 4.7 한 칸). 파이프라인은 `sa_summarize_claude.summary_chain()`이 설정 순번만 호출하고 순번 밖 모델로는 가지 않는다. **성공은 응답 문자열이 아니라 JSON·출력 검증·필수 필드까지 통과한 것**이고, 어느 단계든 실패하면 다음 순번으로 넘긴다(`_checked_summary`, Astra 검토 2026-09-26). 카탈로그 장애 중에도 저장된 모델은 선택 목록에 남긴다. 설정 팝업의 자동 저장은 한 줄로 세워 보내고, 더 새 변경이 줄 서 있으면 앞 응답으로 화면을 덮지 않으며, 실패하면 서버가 마지막으로 확인한 상태로 되돌린다(wm과 같은 방식). 호출: Claude `--model`/`--effort`, Codex `exec -m`·`model_reasoning_effort`(`default`면 플래그 없음), Grok `-m`/`--reasoning-effort`. 옛 `settings.SUMMARY_PRIMARY`는 삭제.
