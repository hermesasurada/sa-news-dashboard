/* SA 대시보드 — 화면 상태·공용 도구·필터·정렬·검색조건(가장 먼저 읽힌다).
   전역 범위를 함께 쓰는 일반 스크립트다. index.html이 app.js → app-cards → app-quote → app-actions →
   app-feed → app-settings → app-boot 순서로 읽는다. */
// 한 페이지 건수 — 카드 15(3열×5줄), PC 리스트 25(2026-11-18 사용자 지시). 폭 기준은 리스트 CSS(≥681px)와 같다.
// _viewMode는 app-cards.js가 정한다(부를 때는 이미 읽혀 있다).
const PAGE_SIZE_CARD = 15;
const PAGE_SIZE_LIST = 25;
function pageSize() {
  return (typeof _viewMode !== 'undefined' && _viewMode === 'list'
          && window.matchMedia('(min-width: 681px)').matches) ? PAGE_SIZE_LIST : PAGE_SIZE_CARD;
}
const DELETE_UNDO_DURATION_MS = 6000;
const READ_UNDO_DURATION_MS = 6000;
let currentOffset = 0;
// 정렬 기준은 이메일 시간 고정(2026-10-01 사용자 지시 — 정렬조건 버튼 삭제). 방향(최신·과거순)만 바꾼다.
const currentSort = 'email_time_et';
let currentOrder = 'desc';   // desc=최신순 / asc=과거순
let trashView = false;
let currentListTotal = null;
let currentQueue = { pending: 0, failed: 0, unread: 0 };

/* ── SVG Icons ── */
const SVG_EYE = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
const SVG_EYE_OFF = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;
const SVG_TRASH = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>`;
// 제목 좌측 액센트 바 색 (ticker_color 감정색과 동일 팔레트)
const ACCENT = { blue:'#3b82f6', green:'#10b981', red:'#ef4444', orange:'#f59e0b', yellow:'#eab308', purple:'#8b5cf6', gray:'#94a3b8' };
const SVG_RESTORE = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>`;

/* ── Shared utilities ── */
const {
  escapeHTML,
  escapeAttr,
  safeExternalURL,
  formatTime,
  formatPrice: fmtPrice,
  formatChangePct: fmtChangePct,
  formatExtendedMarketState,
  isExtendedMarketState,
  formatSummaryModel: summaryModelLabel,
} = window.SAUtils;

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
  return response.json();
}

async function copyArticleId(button) {
  const id = button.dataset.articleId || '';
  if (!id) return;
  const value = `sa ${id}`;   // 서비스 약칭을 붙여 복사(2026-10-12 사용자 지시 — 'sa 9061')
  try {
    await navigator.clipboard.writeText(value);
  } catch (error) {
    const input = document.createElement('input');
    input.value = value;
    document.body.appendChild(input);
    input.select();
    document.execCommand('copy');
    input.remove();
  }
  const original = button.textContent;
  button.textContent = '복사됨';
  button.classList.add('copied');
  setTimeout(() => {
    button.textContent = original;
    button.classList.remove('copied');
  }, 900);
}

/* ── Filters ── */

const FILTERS_CACHE_KEY = 'sa_filters';

async function loadFilters() {
  try {
    const data = await fetchJSON('/api/filters');
    TICKER_ALIASES = data.aliases || {};   // db가 단일 소스
    HOME_NAMES = data.home_names || {};
    applyListings(data.listings);          // 등록부에서 만든 칩 표(company_table)
    try {
      localStorage.setItem(FILTERS_CACHE_KEY,
        JSON.stringify({ aliases: TICKER_ALIASES, home_names: HOME_NAMES, listings: data.listings || {} }));
    } catch (e) {}
  } catch(e) { console.error('필터 로드 실패', e); }
}

// 캐시된 필터를 '동기'로 먼저 적용 → 목록 요청을 /api/filters 응답까지 기다리지 않아도
// 첫 렌더에서 티커 별칭(GOOGL→GOOG)이 정상 적용된다. 성공 시 true.
function loadFiltersFromCache() {
  try {
    const cached = JSON.parse(localStorage.getItem(FILTERS_CACHE_KEY) || 'null');
    if (cached && cached.aliases && cached.listings) {   // 칩 표(listings)가 없는 옛 캐시는 쓰지 않는다
      TICKER_ALIASES = cached.aliases;
      HOME_NAMES = cached.home_names || {};
      applyListings(cached.listings);
      return true;
    }
  } catch (e) {}
  return false;
}

/* ── Sort ── */
// 정렬 기준/방향 UI를 현재 상태에 맞게 반영
function applySortUI() {
  document.getElementById('order-label').textContent = currentOrder === 'asc' ? '과거순' : '최신순';
  document.getElementById('order-toggle').classList.toggle('asc', currentOrder === 'asc');   // 모바일 화살표 방향
  document.getElementById('order-toggle').classList.toggle('alt', currentOrder === 'asc');
}

function toggleOrder() {
  currentOrder = currentOrder === 'desc' ? 'asc' : 'desc';
  applySortUI();
  savePrefs();
  search(0);
}

// ── 검색조건 기본값 로컬 저장/로드 ──
function savePrefs() {
  try {
    localStorage.setItem('sa_prefs', JSON.stringify({
      order: currentOrder,
      unread: document.getElementById('unread-filter').classList.contains('active'),
    }));
  } catch (e) {}
}
function loadPrefs() {
  try {
    const raw = localStorage.getItem('sa_prefs');
    const p = raw ? JSON.parse(raw) : null;
    if (p) {
      if (p.order === 'asc' || p.order === 'desc') currentOrder = p.order;
      if (p.unread) document.getElementById('unread-filter').classList.add('active');
    } else {
      // 최초 방문 — '미읽음만'을 기본값으로 선택
      document.getElementById('unread-filter').classList.add('active');
    }
  } catch (e) {}
  applySortUI();
}

/* ── Params ── */
function getParams(offset) {
  const p = new URLSearchParams();
  const q = document.getElementById('q').value.trim();
  if (q) p.set('q', q);
  p.set('sort_by', currentSort);
  p.set('order', currentOrder);
  if (document.getElementById('unread-filter').classList.contains('active'))
    p.set('unread_only', 'true');
  if (trashView) p.set('deleted', 'true');
  p.set('limit', pageSize());
  p.set('offset', offset);
  return p;
}
