/* SA 대시보드 — 시작 코드 — 반드시 마지막에 읽힌다(init이 앞 파일의 함수·상태를 모두 쓴다).
   전역 범위를 함께 쓰는 일반 스크립트다. index.html이 app.js → app-cards → app-quote → app-actions →
   app-feed → app-settings → app-boot 순서로 읽는다. */
/* ── 팝업이 열려 있는 동안 뒤 화면 스크롤 막기(2026-10-14 사용자 지시, td와 같은 방식) ──
   html의 overflow-x:clip 때문에 body overflow:hidden이 화면 스크롤로 전달되지 않는다. body를 고정하거나
   html overflow를 막으면 상단 고정 영역(sticky)이 배경 뒤에서 사라져서, 스크롤 입력만 막는다. */
(function () {
  const OPEN = '.modal-overlay.show';
  // 화면 배치는 건드리지 않고(상단 고정 영역 유지) 팝업이 열려 있는 동안 휠·터치 스크롤이 뒤 화면을 움직이지
  // 못하게 막는다. 팝업 안의 스크롤 영역은 그 방향으로 더 움직일 수 있을 때만 허용(끝에 닿으면 뒤로 안 번짐).
  let active = false, touchY = 0;
  function canScroll(target, dy, roots) {
    for (let el = target; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
      const st = getComputedStyle(el);
      if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 1) {
        if (dy > 0 && el.scrollTop + el.clientHeight < el.scrollHeight - 1) return true;
        if (dy < 0 && el.scrollTop > 0) return true;
      }
      if (roots.includes(el)) return false;
    }
    return false;
  }
  function block(e, dy) {
    if (!dy) return;
    const roots = [...document.querySelectorAll(OPEN)];
    if (!canScroll(e.target, dy, roots) && e.cancelable) e.preventDefault();
  }
  const onWheel = (e) => block(e, e.deltaY);
  const onTouchStart = (e) => { touchY = e.touches[0] ? e.touches[0].clientY : 0; };
  const onTouchMove = (e) => { const y = e.touches[0] ? e.touches[0].clientY : touchY; block(e, touchY - y); touchY = y; };
  const onKey = (e) => {
    if (!['PageDown', 'PageUp', 'End', 'Home', ' ', 'ArrowDown', 'ArrowUp'].includes(e.key)) return;
    if (e.target.closest && e.target.closest('input, textarea, select, [contenteditable="true"]')) return;
    const roots = [...document.querySelectorAll(OPEN)];
    if (!roots.some(r => r.contains(e.target))) e.preventDefault();
  };
  function sync() {
    const open = !!document.querySelector(OPEN);
    if (open === active) return;
    active = open;
    const fn = open ? 'addEventListener' : 'removeEventListener';
    window[fn]('wheel', onWheel, { passive: false });
    window[fn]('touchstart', onTouchStart, { passive: true });
    window[fn]('touchmove', onTouchMove, { passive: false });
    window[fn]('keydown', onKey);
  }
  const start = () => new MutationObserver(sync).observe(document.body,
    { subtree: true, attributes: true, attributeFilter: ['class', 'hidden'] });
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();

/* ── Init ── */
async function init() {
  applyReaderFont();               // 저장된 글꼴을 로드 시점에 반영
  applyReaderSize();
  // 첫 방문도 필터 목록과 기사 목록을 병렬로 요청한다. 발행 시 티커가 이미
  // 정규화되므로 필터 응답이 카드 첫 렌더를 막을 이유가 없다.
  const fromCache = loadFiltersFromCache();
  const filtersReady = loadFilters();
  if (!fromCache) await filtersReady;   // 첫 방문: 칩 표(OTC → 자국 상장) 없이 그리지 않게
  loadPrefs();                     // 로컬에 저장된 검색조건 기본값 적용
  const savedOffset = restoreFromURL(); // URL이 있으면 우선 (공유 링크)
  search(savedOffset);
  startNotificationPolling();
}
init();
