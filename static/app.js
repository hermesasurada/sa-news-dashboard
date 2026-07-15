const PAGE_SIZE = 15;
let currentOffset = 0;
let currentSort = 'email_time_et';
let currentOrder = 'desc';   // desc=최신순 / asc=과거순
let trashView = false;

/* ── SVG Icons ── */
const SVG_EYE = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
const SVG_EYE_OFF = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;
const SVG_TRASH = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>`;
// 제목 좌측 액센트 바 색 (ticker_color 감정색과 동일 팔레트)
const ACCENT = { blue:'#3b82f6', green:'#10b981', red:'#ef4444', orange:'#f59e0b', yellow:'#eab308', purple:'#8b5cf6', gray:'#94a3b8' };
const SVG_RESTORE = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>`;

/* ── Filters ── */
let allTickers = [];

async function loadFilters() {
  try {
    const res = await fetch('/api/filters');
    const data = await res.json();
    allTickers = data.tickers || [];
    TICKER_ALIASES = data.aliases || {};   // db가 단일 소스
  } catch(e) { console.error('필터 로드 실패', e); }
}

/* ── 티커 선택 모달 ── */
// 해외상장 티커는 자국 표기(삼성전자 / AIR.PA)로 보여 가독성↑
function tickerDisplay(raw) {
  const fl = FOREIGN_LISTINGS[raw];
  return fl ? (fl.kr ? fl.name : fl.home) : raw;
}
function updateTickerLabel() {
  const val = document.getElementById('ticker-filter').value;
  const btn = document.getElementById('ticker-btn');
  const lbl = document.getElementById('ticker-btn-label');
  if (val) { lbl.textContent = tickerDisplay(val); btn.classList.add('active'); }
  else     { lbl.textContent = '전체 티커'; btn.classList.remove('active'); }
}
function openTickerModal() {
  document.getElementById('ticker-search').value = '';
  document.getElementById('ticker-modal').classList.add('show');
  renderTickerList();
  setTimeout(() => document.getElementById('ticker-search').focus(), 30);
}
function closeTickerModal() {
  document.getElementById('ticker-modal').classList.remove('show');
}
function setTicker(val) {
  document.getElementById('ticker-filter').value = val;
  updateTickerLabel();
  closeTickerModal();
  search(0);
}
function renderTickerList() {
  const q = document.getElementById('ticker-search').value.trim().toLowerCase();
  const cur = document.getElementById('ticker-filter').value;
  const matched = allTickers.filter(t => {
    if (!q) return true;
    const fl = FOREIGN_LISTINGS[t];
    const hay = (t + ' ' + (fl ? fl.home + ' ' + fl.name : '')).toLowerCase();
    return hay.includes(q);
  });
  const allChip = `<div class="tk-chip all ${!cur ? 'active' : ''}" onclick="setTicker('')">전체</div>`;
  if (matched.length === 0) {
    document.getElementById('ticker-list').innerHTML = allChip + '<div class="tk-empty">일치하는 티커가 없습니다</div>';
    return;
  }
  const chips = matched.map(t => {
    const fl = FOREIGN_LISTINGS[t];
    const sub = fl ? `<span class="sub">${fl.kr ? fl.name : fl.home}</span>` : '';
    return `<div class="tk-chip ${t === cur ? 'active' : ''}" onclick="setTicker('${t}')">${t}${sub}</div>`;
  }).join('');
  document.getElementById('ticker-list').innerHTML = allChip + chips;
}

/* ── Sort ── */
// 정렬 기준/방향 UI를 현재 상태에 맞게 반영
function applySortUI() {
  document.getElementById('sort-label').textContent = currentSort === 'last_modified' ? '수정시간순' : '이메일시간순';
  document.getElementById('sort-toggle').classList.toggle('alt', currentSort === 'last_modified');
  document.getElementById('order-label').textContent = currentOrder === 'asc' ? '과거순' : '최신순';
  document.getElementById('order-toggle').classList.toggle('alt', currentOrder === 'asc');
}

function toggleSort() {
  currentSort = currentSort === 'email_time_et' ? 'last_modified' : 'email_time_et';
  applySortUI();
  savePrefs();
  search(0);
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
      sort: currentSort,
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
      if (p.sort === 'last_modified' || p.sort === 'email_time_et') currentSort = p.sort;
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
  const ticker = document.getElementById('ticker-filter').value;
  if (q) p.set('q', q);
  if (ticker) p.set('ticker', ticker);
  p.set('sort_by', currentSort);
  p.set('order', currentOrder);
  if (document.getElementById('unread-filter').classList.contains('active'))
    p.set('unread_only', 'true');
  if (trashView) p.set('deleted', 'true');
  p.set('limit', PAGE_SIZE);
  p.set('offset', offset);
  return p;
}

function formatTime(et) {
  if (!et) return '';
  const m = et.match(/(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2})/);
  if (!m) return et;
  return `${m[2]}/${m[3]} ${m[4]}`;
}

// 동일 종목(클래스 차이) 병합 규칙 — 단일 소스는 db.TICKER_ALIASES.
// loadFilters()가 /api/filters에서 받아와 채움 (실패 시 빈 맵 = 병합 없이 원본 유지).
let TICKER_ALIASES = {};
const canonTicker = (t) => TICKER_ALIASES[t.toUpperCase()] || t;

// 미국 메인거래소(나스닥/NYSE) 미상장 — OTC ADR/해외상장 티커를 자국 시장 티커로 매핑.
//   kr:true  → 한글명 배지 + 마우스오버 티커 (한국 기업)
//   kr:false → 자국 티커 배지 + 마우스오버 영문 기업명 (그 외 외국 기업)
const FOREIGN_LISTINGS = {
  // 🇰🇷 한국
  SSNLF:{home:'005930.KS', name:'삼성전자', kr:true},
  HXSCL:{home:'000660.KS', name:'SK하이닉스', kr:true},
  LGEIY:{home:'066570.KS', name:'LG전자', kr:true},
  NHNCF:{home:'035420.KS', name:'네이버', kr:true},
  // 🇪🇺 유럽
  EADSY:{home:'AIR.PA', name:'Airbus'}, EADSF:{home:'AIR.PA', name:'Airbus'},
  ADDYY:{home:'ADS.DE', name:'Adidas'},
  BMWKY:{home:'BMW.DE', name:'BMW'},
  VWAGY:{home:'VOW3.DE', name:'Volkswagen'},
  SIEGY:{home:'SIE.DE', name:'Siemens'},
  DLAKF:{home:'LHA.DE', name:'Lufthansa'}, DLAKY:{home:'LHA.DE', name:'Lufthansa'},
  DHER:{home:'DHER.DE', name:'Delivery Hero'},
  SAFRF:{home:'SAF.PA', name:'Safran'}, SAFRY:{home:'SAF.PA', name:'Safran'},
  DUAVF:{home:'AM.PA', name:'Dassault Aviation'},
  ENI:{home:'ENI.MI', name:'Eni'},
  NTOIY:{home:'NESTE.HE', name:'Neste'},
  IBDRY:{home:'IBE.MC', name:'Iberdrola'}, IBDSF:{home:'IBE.MC', name:'Iberdrola'},
  CAMRF:{home:'CAMX.ST', name:'Camurus'},
  SAABF:{home:'SAAB-B.ST', name:'Saab'}, SAABY:{home:'SAAB-B.ST', name:'Saab'},
  RYCEY:{home:'RR.L', name:'Rolls-Royce'}, RYCEF:{home:'RR.L', name:'Rolls-Royce'},
  BAESY:{home:'BA.L', name:'BAE Systems'},
  HEINY:{home:'HEIA.AS', name:'Heineken'},
  RNMBF:{home:'RHM.DE', name:'Rheinmetall'}, RNMBY:{home:'RHM.DE', name:'Rheinmetall'},
  // 🇯🇵 일본
  NTDOY:{home:'7974.T', name:'Nintendo'}, NTDOF:{home:'7974.T', name:'Nintendo'},
  SFTBY:{home:'9984.T', name:'SoftBank Group'}, SFTBF:{home:'9984.T', name:'SoftBank Group'},
  NINOY:{home:'7731.T', name:'Nikon'},
  HTHIY:{home:'6501.T', name:'Hitachi'}, HTHIF:{home:'6501.T', name:'Hitachi'},
  // 🇨🇳🇹🇼🇭🇰
  BYDDY:{home:'1211.HK', name:'BYD'}, BYDDF:{home:'1211.HK', name:'BYD'},
  HNHPF:{home:'2317.TW', name:'Hon Hai (Foxconn)'},
  FXCOF:{home:'2354.TW', name:'Foxconn Technology'},
  IVBIY:{home:'1801.HK', name:'Innovent Biologics'}, IVBXF:{home:'1801.HK', name:'Innovent Biologics'},
  LNVGY:{home:'0992.HK', name:'Lenovo'},
  // 🌏 기타
  QABSY:{home:'QAN.AX', name:'Qantas'},
  SYAAF:{home:'SYR.AX', name:'Syrah Resources'}, SRHYY:{home:'SYR.AX', name:'Syrah Resources'},
  DBSDY:{home:'D05.SI', name:'DBS Group'},
  BDRBF:{home:'BBD-B.TO', name:'Bombardier'}, BDRAF:{home:'BBD-B.TO', name:'Bombardier'}, BOMBF:{home:'BBD-B.TO', name:'Bombardier'},
  KRKNF:{home:'PNG.V', name:'Kraken Robotics'},
  TAKOF:{home:'FLT.V', name:'Volatus Aerospace'},
};

function extractTickers(a) {
  // LLM이 관련성 판단해 선별한 ticker 필드만 사용
  // ($TICKER 정규식 무조건 수집은 제거 — 스치는 언급까지 배지로 붙는 문제)
  const map = new Map();
  const rawTicker = (a.ticker || '').trim();
  if (rawTicker && rawTicker.toUpperCase() !== 'NONE') {
    const tks = rawTicker.split(/[,·\s]+/).map(t => t.trim()).filter(t => /^[A-Z0-9.]{1,6}$/.test(t));
    const names = (a.company_name || '').split(/·/).map(n => n.trim()).filter(Boolean);
    tks.forEach((t, i) => { const c = canonTicker(t); if (c && !map.has(c)) map.set(c, names[i] || names[0] || ''); });
  }
  return [...map.entries()].map(([ticker, name]) => ({ ticker, name }));
}

// parse_method(db) → 카드에 표기할 수집방식 라벨. NULL(기존행)이면 빈값.
function parseMethodLabel(m) {
  if (!m) return '';
  if (m.startsWith('jina')) return 'Jina';
  if (m.startsWith('playwright')) return 'Playwright';
  if (m.startsWith('curl_cffi')) return 'curl';
  return m;
}

// summary_model(db) → 요약한 LLM+버전 라벨. NULL(기존행)이면 빈값.
function summaryModelLabel(m) {
  if (!m) return '';
  let mm;
  if ((mm = m.match(/^claude-opus-(\d+)-(\d+)/)))   return `Claude Opus ${mm[1]}.${mm[2]}`;
  if ((mm = m.match(/^claude-sonnet-(\d+)/)))        return `Claude Sonnet ${mm[1]}`;
  if ((mm = m.match(/^claude-haiku-(\d+)-(\d+)/)))   return `Claude Haiku ${mm[1]}.${mm[2]}`;
  if (m.startsWith('claude'))                        return 'Claude';
  if ((mm = m.match(/^grok-([\d.]+)/)))              return `Grok ${mm[1]}`;
  if (m.startsWith('grok'))                          return 'Grok';
  return m;
}

/* ── Card Render ── */
function renderCard(a) {
  const details = a.summary_details.map(d => `<li>${d}</li>`).join('');
  const timeLabel = formatTime(a.email_time_et);
  const emailIdLabel = a.email_id ? `ID:${a.email_id}` : '';
  const footerMeta = [emailIdLabel, timeLabel].filter(Boolean).join(' · ');
  const methodLabel = parseMethodLabel(a.parse_method);
  const modelLabel = summaryModelLabel(a.summary_model);
  const metaLine2 = [methodLabel, modelLabel].filter(Boolean).join(' · ');
  const isRead = !!a.is_read;
  const unreadDot = !isRead ? '<span class="unread-dot" title="미읽음"></span>' : '';
  const readBtnClass = isRead ? 'read-btn done' : 'read-btn';
  const readBtnTitle = isRead ? '읽음 취소' : '읽음 처리';
  const hasOrig = !!a.original_title;
  const originalTitle = hasOrig ? `<div class="card-orig-title">${a.original_title}</div>` : '';

  const tickers = extractTickers(a);
  const tickerBadges = tickers.map((t, i) => {
    const color = i === 0 ? (a.ticker_color || 'blue') : 'gray';
    const fl = FOREIGN_LISTINGS[t.ticker];
    let label, companyName, quoteTicker;
    if (fl && fl.kr)   { label = fl.name; companyName = fl.name; quoteTicker = fl.home; }
    else if (fl)       { label = fl.home; companyName = fl.name || t.name; quoteTicker = fl.home; }
    else               { label = t.ticker; companyName = t.name || t.ticker; quoteTicker = t.ticker; }
    const attrs = [
      `data-ticker="${escapeAttr(t.ticker)}"`,
      `data-quote-ticker="${escapeAttr(quoteTicker)}"`,
      `data-company="${escapeAttr(companyName || '')}"`,
      'role="button"',
      'tabindex="0"',
    ].join(' ');
    return `<span class="ticker-badge ticker-${color} ticker-live"${attrs}>${label}</span>`;
  }).join('');

  // 키워드 태그는 표시하지 않음 — 티커 배지만 사용
  const combinedBadges = tickerBadges;

  // 모바일 스와이프 배경 (telegram-digest 이식) — PC는 @media(hover:hover)에서 숨김
  const swipeEye = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;

  return `
<div class="swipe-row">
  <div class="swipe-action left" aria-hidden="true">${swipeEye}<span>읽음</span></div>
  <div class="swipe-action right" aria-hidden="true"><span>읽음</span>${swipeEye}</div>
<div class="card${!isRead ? ' card-unread' : ''}" data-id="${a.id}" data-read="${isRead ? '1' : '0'}" style="--accent:${ACCENT[a.ticker_color] || ACCENT.blue}">
  <div class="card-title-row">
    ${unreadDot}
    <h2 class="card-title">${a.headline}</h2>
  </div>
  ${originalTitle}
  <hr class="card-divider">
  ${a.summary_core ? `<div class="card-summary"><strong>핵심</strong>&nbsp;${a.summary_core}</div>` : ''}
  <div class="card-details">
    ${a.summary_core ? '<strong>상세</strong>' : ''}
    <ul>${details}</ul>
  </div>
  ${combinedBadges ? `<div class="card-tickers">${combinedBadges}</div>` : ''}
  <div class="card-footer">
    <span class="footer-left">${footerMeta}${metaLine2 ? `<span class="footer-method">${metaLine2}</span>` : ''}</span>
    <div class="footer-actions">
      ${trashView ? '' : `<button class="${readBtnClass}" onclick="toggleRead(${a.id}, this)" title="${readBtnTitle}">${isRead ? SVG_EYE_OFF : SVG_EYE}</button>`}
      <a class="link-btn" href="${a.article_url}" target="_blank" rel="noopener">원문보기</a>
      ${trashView
        ? `<button class="restore-btn" onclick="restoreCard(${a.id}, this)" title="복원">${SVG_RESTORE}복원</button>`
        : `<button class="delete-btn" onclick="deleteCard(${a.id}, this)" title="삭제">${SVG_TRASH}</button>`}
    </div>
  </div>
</div>
</div>`;
}

/* ── 모바일 스와이프 → 읽음처리 (telegram-digest 이식) ──
   터치 이벤트만 사용 → 데스크톱 무영향. 좌/우 양방향, 미읽음 카드만. */
const SWIPE_INTERACTIVE = '.read-btn,.link-btn,.delete-btn,.restore-btn,.ticker-badge,a,button';

/* ── Ticker popover: company + portfolio v2 live change ── */
const quoteCache = new Map(); // quoteTicker → { at, data } | { at, error }
const QUOTE_TTL_MS = 60_000;

function escapeAttr(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function fmtPrice(price, currency) {
  if (price == null || !Number.isFinite(Number(price))) return '—';
  const n = Number(price);
  const cur = (currency || '').toUpperCase();
  if (cur === 'KRW') return `₩${Math.round(n).toLocaleString('ko-KR')}`;
  if (cur === 'USD') return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (cur === 'EUR') return `€${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (cur === 'JPY') return `¥${Math.round(n).toLocaleString('en-US')}`;
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 4 })}${cur ? ' ' + cur : ''}`;
}

function fmtChangePct(pct) {
  if (pct == null || !Number.isFinite(Number(pct))) return { text: '—', cls: 'flat' };
  const n = Number(pct);
  const cls = n > 0 ? 'up' : n < 0 ? 'down' : 'flat';
  const sign = n > 0 ? '+' : '';
  return { text: `${sign}${n.toFixed(2)}%`, cls };
}

function ensureTickerPopover() {
  let el = document.getElementById('ticker-quote-pop');
  if (el) return el;
  el = document.createElement('div');
  el.id = 'ticker-quote-pop';
  el.className = 'ticker-quote-pop';
  el.hidden = true;
  el.setAttribute('role', 'dialog');
  el.innerHTML = `
    <div class="tqp-head">
      <span class="tqp-name"></span>
    </div>
    <div class="tqp-body">
      <span class="tqp-price">…</span>
      <span class="tqp-chg flat">…</span>
    </div>
    <div class="tqp-ext" hidden><span class="tqp-ext-label"></span><span class="tqp-ext-chg flat"></span></div>
    <div class="tqp-meta"></div>`;
  document.body.appendChild(el);
  return el;
}

/* ── 종목명 캐시 (localStorage) — 포트폴리오/NASDAQ에서 확인된 이름 저장 ── */
const nameCache = (() => {
  try { return JSON.parse(localStorage.getItem('sa_ticker_names') || '{}'); }
  catch (e) { return {}; }
})();
function rememberName(ticker, name) {
  if (!ticker || !name || name.toUpperCase() === ticker.toUpperCase()) return;
  if (nameCache[ticker] === name) return;
  nameCache[ticker] = name;
  try { localStorage.setItem('sa_ticker_names', JSON.stringify(nameCache)); } catch (e) {}
}

function hideTickerPopover() {
  const el = document.getElementById('ticker-quote-pop');
  if (el) el.hidden = true;
}

function positionTickerPopover(el, anchor) {
  const r = anchor.getBoundingClientRect();
  const pad = 8;
  el.hidden = false;
  // measure after show
  const w = el.offsetWidth || 200;
  const h = el.offsetHeight || 80;
  let left = r.left;
  let top = r.top - h - 10;
  if (top < pad) top = r.bottom + 10;
  if (left + w > window.innerWidth - pad) left = window.innerWidth - w - pad;
  if (left < pad) left = pad;
  el.style.left = `${Math.round(left)}px`;
  el.style.top = `${Math.round(top)}px`;
}

async function fetchPortfolioQuote(quoteTicker) {
  const key = String(quoteTicker || '').toUpperCase();
  const hit = quoteCache.get(key);
  if (hit && Date.now() - hit.at < QUOTE_TTL_MS) return hit;
  try {
    const res = await fetch(`/api/price-quote?ticker=${encodeURIComponent(key)}`);
    if (!res.ok) {
      const err = { at: Date.now(), error: true, status: res.status };
      quoteCache.set(key, err);
      return err;
    }
    const data = await res.json();
    const packed = { at: Date.now(), data };
    quoteCache.set(key, packed);
    return packed;
  } catch (e) {
    const err = { at: Date.now(), error: true, message: e.message };
    quoteCache.set(key, err);
    return err;
  }
}

function renderTickerPopoverContent(el, companyFallback, quoteTicker, packed) {
  const name = el.querySelector('.tqp-name');
  const price = el.querySelector('.tqp-price');
  const chg = el.querySelector('.tqp-chg');
  const ext = el.querySelector('.tqp-ext');
  const extLabel = el.querySelector('.tqp-ext-label');
  const extChg = el.querySelector('.tqp-ext-chg');
  const meta = el.querySelector('.tqp-meta');
  ext.hidden = true;

  const d = (!packed.error && packed.data) ? packed.data : null;
  // 종목명: 서버(포트폴리오/NASDAQ) > 로컬 캐시 > 기사 회사명 > 티커
  const bestName = (d && d.name) || nameCache[quoteTicker] || companyFallback || quoteTicker;
  name.textContent = bestName;
  if (d && d.name) rememberName(quoteTicker, d.name);

  if (!d || d.found === false || d.current_price == null) {
    price.textContent = '시세 없음';
    chg.textContent = '';
    chg.className = 'tqp-chg flat';
    meta.textContent = packed.error ? '포트폴리오 서버 연결 실패' : '포트폴리오 시세 미제공';
    return;
  }
  price.textContent = fmtPrice(d.current_price, d.currency);
  const { text, cls } = fmtChangePct(d.change_pct);
  chg.textContent = text;
  chg.className = `tqp-chg ${cls}`;
  // 애프터/프리장: 전일대비 + 장외 등락 병기
  if (d.extended_change_pct != null) {
    const e = fmtChangePct(d.extended_change_pct);
    extLabel.textContent = d.market_label || '장외';
    extChg.textContent = e.text;
    extChg.className = `tqp-ext-chg ${e.cls}`;
    ext.hidden = false;
  }
  const bits = [];
  if (d.market_label) bits.push(d.market_label);
  bits.push('전일대비');
  meta.textContent = bits.join(' · ');
}

async function showTickerQuote(badge) {
  const quoteTicker = (badge.dataset.quoteTicker || badge.dataset.ticker || '').toUpperCase();
  const company = badge.dataset.company || '';
  if (!quoteTicker) return;
  const el = ensureTickerPopover();
  el.dataset.activeTicker = quoteTicker;
  // loading state
  el.querySelector('.tqp-name').textContent = company || nameCache[quoteTicker] || quoteTicker;
  el.querySelector('.tqp-price').textContent = '불러오는 중…';
  el.querySelector('.tqp-chg').textContent = '';
  el.querySelector('.tqp-chg').className = 'tqp-chg flat';
  el.querySelector('.tqp-ext').hidden = true;
  el.querySelector('.tqp-meta').textContent = 'portfolio v2';
  positionTickerPopover(el, badge);
  const packed = await fetchPortfolioQuote(quoteTicker);
  if (el.dataset.activeTicker !== quoteTicker) return; // superseded
  renderTickerPopoverContent(el, company, quoteTicker, packed);
  positionTickerPopover(el, badge);
}

function attachTickerQuoteHandlers() {
  document.querySelectorAll('.ticker-badge.ticker-live').forEach((badge) => {
    if (badge.dataset.quoteBound) return;
    badge.dataset.quoteBound = '1';
    const open = (e) => {
      e.preventDefault();
      e.stopPropagation();
      showTickerQuote(badge);
    };
    badge.addEventListener('click', open);
    badge.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') open(e);
    });
  });
}

// Close popover on outside tap / scroll / escape
document.addEventListener('click', (e) => {
  if (e.target.closest('.ticker-badge.ticker-live')) return;
  if (e.target.closest('#ticker-quote-pop')) return;
  hideTickerPopover();
}, true);
document.addEventListener('scroll', hideTickerPopover, true);
window.addEventListener('resize', hideTickerPopover);

function attachSwipeHandlers() {
  if (trashView) return;  // 휴지통 뷰: 스와이프 없음 (read-btn 부재)
  document.querySelectorAll('.swipe-row').forEach((row) => {
    const card = row.querySelector('.card');
    const left = row.querySelector('.swipe-action.left');
    const right = row.querySelector('.swipe-action.right');
    if (!card) return;
    let startX = 0, startY = 0, dx = 0, axis = null, active = false;

    const reset = (animate) => {
      card.style.transition = animate ? 'transform .2s ease' : 'none';
      card.style.transform = 'translateX(0)';
      if (left) left.style.opacity = '0';
      if (right) right.style.opacity = '0';
    };

    row.addEventListener('touchstart', (e) => {
      if (e.touches.length !== 1) return;
      if (e.target.closest(SWIPE_INTERACTIVE)) return;   // 버튼/링크 탭 보존
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      dx = 0; axis = null; active = true;
      card.style.transition = 'none';
    }, { passive: true });

    row.addEventListener('touchmove', (e) => {
      if (!active) return;
      dx = e.touches[0].clientX - startX;
      const dy = e.touches[0].clientY - startY;
      if (axis === null) {
        if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
        axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
        if (axis === 'y') { active = false; return; }  // 세로 스크롤 허용
      }
      if (axis !== 'x') return;
      e.preventDefault();                                // 세로 스크롤 차단
      row.classList.add('swiping');                      // 스와이프 중에만 overflow 클리핑(그림자는 평소 노출)
      const w = card.offsetWidth || 320;
      const clamped = Math.max(-w, Math.min(w, dx));
      card.style.transform = `translateX(${clamped}px)`;
      const progress = Math.min(1, Math.abs(clamped) / (w * 0.35));
      if (clamped > 0) { if (left) left.style.opacity = String(progress); if (right) right.style.opacity = '0'; }
      else { if (right) right.style.opacity = String(progress); if (left) left.style.opacity = '0'; }
    }, { passive: false });

    const unswipe = () => setTimeout(() => row.classList.remove('swiping'), 220);
    row.addEventListener('touchend', () => {
      if (!active) return;
      active = false;
      if (axis !== 'x') { reset(false); row.classList.remove('swiping'); return; }
      const w = card.offsetWidth || 320;
      const threshold = Math.max(90, w * 0.35);
      if (Math.abs(dx) >= threshold && card.dataset.read !== '1') {
        // 미읽음일 때만 읽음처리(강제 읽음). 이미 읽음이면 스냅백.
        toggleRead(parseInt(card.dataset.id), card.querySelector('.read-btn'));
        if (document.getElementById('unread-filter').classList.contains('active')) {
          const dir = dx > 0 ? 1 : -1;                   // 스와이프 방향으로 밀어내고 toggleRead가 페이드+제거(래퍼째)
          card.style.transition = 'transform .2s ease, opacity .2s ease';
          card.style.transform = `translateX(${dir * w}px)`;
          card.style.opacity = '0';
        } else {
          reset(true); unswipe();                        // 전체 보기: 읽음처리만, 제자리 복귀
        }
      } else {
        reset(true); unswipe();                          // 스냅백
      }
    });
  });
}

/* ── Read Toggle ── */
async function toggleRead(id, btn) {
  const card = btn.closest('.card');
  const isCurrentlyRead = card.dataset.read === '1';
  const newRead = !isCurrentlyRead;
  try {
    const res = await fetch(`/api/articles/${id}/read`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({is_read: newRead}),
    });
    if (!res.ok) return;
    card.dataset.read = newRead ? '1' : '0';
    if (newRead) {
      card.classList.remove('card-unread');
      const dot = card.querySelector('.unread-dot');
      if (dot) dot.remove();
      btn.className = 'read-btn done';
      btn.title = '읽음 취소';
      btn.innerHTML = SVG_EYE_OFF;
      // #2: 미읽음 필터 활성 중이면 카드 즉시 제거 (swipe-row 래퍼째)
      if (document.getElementById('unread-filter').classList.contains('active')) {
        card.style.transition = 'opacity 0.3s';
        card.style.opacity = '0';
        setTimeout(() => (card.closest('.swipe-row') || card).remove(), 300);
      }
    } else {
      card.classList.add('card-unread');
      const titleRow = card.querySelector('.card-title-row');
      if (titleRow) titleRow.insertAdjacentHTML('afterbegin', '<span class="unread-dot" title="미읽음"></span>');
      btn.className = 'read-btn';
      btn.title = '읽음 처리';
      btn.innerHTML = SVG_EYE;
    }
  } catch(e) { console.error('읽음 상태 변경 실패', e); }
}

/* ── #6: Delete (즉시 삭제) ── */
function deleteCard(articleId, element) {
  const card = element.closest('.card');
  if (card.dataset.deleting) return;
  card.dataset.deleting = '1';
  card.classList.add('card-deleting');

  fetch(`/api/articles/${articleId}`, { method: 'DELETE' })
    .then(res => {
      if (res.ok) {
        card.remove();
        // 즉시 삭제 완료 → 3초간 '취소' 버튼 노출
        showToast('기사를 삭제했습니다', '취소', () => undoDelete(articleId), 3000);
      } else {
        card.classList.remove('card-deleting');
        delete card.dataset.deleting;
        showToast('삭제 실패', null, null);
      }
    })
    .catch(() => {
      card.classList.remove('card-deleting');
      delete card.dataset.deleting;
      showToast('삭제 중 오류 발생', null, null);
    });
}

/* ── 삭제 취소(복원) ── */
function undoDelete(articleId) {
  fetch(`/api/articles/${articleId}/restore`, { method: 'POST' })
    .then(res => {
      if (res.ok) {
        search(currentOffset);  // 목록 새로고침 → 복원된 기사 다시 표시
      } else {
        showToast('취소 실패', null, null);
      }
    })
    .catch(() => showToast('취소 중 오류 발생', null, null));
}

/* ── Toast ── */
let _toastTimer = null;
let _toastUndoFn = null;

function showToast(message, actionLabel, actionFn, duration = 4500) {
  const toast = document.getElementById('toast');
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastUndoFn = actionFn;
  toast.innerHTML = `<span>${message}</span>`
    + (actionLabel ? `<button class="toast-action" onclick="toastAction()">${actionLabel}</button>` : '');
  toast.classList.add('show');
  _toastTimer = setTimeout(() => {
    toast.classList.remove('show');
    _toastUndoFn = null;
  }, duration);
}

function toastAction() {
  if (_toastUndoFn) _toastUndoFn();
  document.getElementById('toast').classList.remove('show');
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastUndoFn = null;
}

/* ── Pagination ── */
function renderPagination(total, offset) {
  const pag = document.getElementById('pagination');
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE);
  if (totalPages <= 1) { pag.innerHTML = ''; return; }

  let html = `<button onclick="search(${(currentPage-1)*PAGE_SIZE})" ${currentPage===0?'disabled':''}>◀ 이전</button>`;
  // 한 번에 최대 10개씩 블록 단위로 노출 (1~10, 11~20 …)
  const BLOCK = 10;
  const start = Math.floor(currentPage / BLOCK) * BLOCK;
  const end = Math.min(totalPages - 1, start + BLOCK - 1);
  for (let i = start; i <= end; i++) {
    html += `<button class="${i===currentPage?'active':''}" onclick="search(${i*PAGE_SIZE})">${i+1}</button>`;
  }
  html += `<button onclick="search(${(currentPage+1)*PAGE_SIZE})" ${currentPage===totalPages-1?'disabled':''}>다음 ▶</button>`;
  html += `<span class="page-info">${total}건 / ${totalPages}페이지</span>`;
  pag.innerHTML = html;
}

/* ── #9: URL 상태 동기화 ── */
function syncURL(params) {
  const url = new URL(location.href);
  url.search = params.toString();
  history.replaceState(null, '', url.toString());
}

function restoreFromURL() {
  const sp = new URLSearchParams(location.search);
  if (sp.has('q'))           document.getElementById('q').value = sp.get('q');
  if (sp.has('ticker'))    { document.getElementById('ticker-filter').value = sp.get('ticker'); updateTickerLabel(); }
  if (sp.has('unread_only')) document.getElementById('unread-filter').classList.add('active');
  // URL이 정렬을 지정하면 로컬 기본값보다 우선 (공유 링크)
  if (sp.has('sort_by')) currentSort = sp.get('sort_by') === 'last_modified' ? 'last_modified' : 'email_time_et';
  if (sp.has('order'))   currentOrder = sp.get('order') === 'asc' ? 'asc' : 'desc';
  applySortUI();
  return parseInt(sp.get('offset') || '0');
}

/* ── #7: 새 기사 알림 polling ── */
let lastKnownTotal = 0;

function showNewArticlesBanner(newCount) {
  const banner = document.getElementById('new-articles-banner');
  banner.textContent = `🆕 새 기사 ${newCount}건 도착 — 클릭해서 새로고침`;
  banner.style.display = 'block';
}

function dismissBanner() {
  document.getElementById('new-articles-banner').style.display = 'none';
  lastKnownTotal = 0;
  search(0);
}

function startNotificationPolling() {
  setInterval(async () => {
    if (lastKnownTotal === 0) return;
    try {
      const res = await fetch('/api/articles?limit=1&sort_by=last_modified');
      const { total } = await res.json();
      if (total > lastKnownTotal) {
        showNewArticlesBanner(total - lastKnownTotal);
      }
    } catch(e) {}
  }, 5 * 60 * 1000);
}

/* ── Search ── */
async function search(offset = 0) {
  currentOffset = offset;
  const params = getParams(offset);

  // #9: URL 동기화
  syncURL(params);

  const cardsEl = document.getElementById('cards');
  const statsEl = document.getElementById('stats');
  cardsEl.innerHTML = '<div class="empty-state">불러오는 중...</div>';

  try {
    const [res, qRes] = await Promise.all([
      fetch('/api/articles?' + params.toString()),
      fetch('/api/queue_stats'),
    ]);
    const data = await res.json();
    const qData = await qRes.json();

    const pendingBadge = qData.pending > 0
      ? ` <span class="pending-badge">대기 ${qData.pending}건</span>`
      : '';
    const unreadBadge = qData.unread > 0
      ? ` <span class="unread-badge">안읽음 ${qData.unread}건</span>`
      : '';
    const badges = trashView ? '' : (pendingBadge + unreadBadge);
    const trashLabel = trashView ? '🗑 휴지통 · ' : '';

    if (data.items.length === 0) {
      const hasFilter = !!(document.getElementById('q').value.trim()
        || document.getElementById('ticker-filter').value
        || document.getElementById('unread-filter').classList.contains('active'));
      let msg, icon;
      if (trashView)       { icon = '🗑'; msg = '휴지통이 비어있습니다.'; }
      else if (hasFilter)  { icon = '🔍'; msg = '조건에 해당하는 기사가 없습니다.'; }
      else                 { icon = '📭'; msg = '표시할 기사가 없습니다.'; }
      cardsEl.innerHTML = `<div class="empty-state"><span class="empty-icon">${icon}</span>${msg}</div>`;
      document.getElementById('pagination').innerHTML = '';
      statsEl.innerHTML = badges;
      return;
    }

    statsEl.innerHTML = trashLabel + `${data.total}건 (${offset+1}~${Math.min(offset+PAGE_SIZE, data.total)}번째)` + badges;
    cardsEl.innerHTML = data.items.map(renderCard).join('');
    attachSwipeHandlers();
    attachTickerQuoteHandlers();
    renderPagination(data.total, offset);

    // #7: 필터 없는 1페이지 결과로 기준 total 갱신
    const qVal = document.getElementById('q').value.trim();
    const tVal = document.getElementById('ticker-filter').value;
    const uVal = document.getElementById('unread-filter').classList.contains('active');
    if (!qVal && !tVal && !uVal && offset === 0) {
      lastKnownTotal = data.total;
      document.getElementById('new-articles-banner').style.display = 'none';
    }
  } catch(e) {
    cardsEl.innerHTML = '<div class="empty-state">데이터를 불러오지 못했습니다.</div>';
    console.error(e);
  }
}

/* ── Filter Controls ── */
function toggleUnreadFilter() {
  document.getElementById('unread-filter').classList.toggle('active');
  savePrefs();
  search(0);
}

function toggleTrashView() {
  trashView = !trashView;
  document.getElementById('trash-view').classList.toggle('active', trashView);
  // 휴지통 보기에서는 미읽음 필터 해제 (혼동 방지)
  if (trashView) document.getElementById('unread-filter').classList.remove('active');
  search(0);
}

function reset() {
  document.getElementById('q').value = '';
  document.getElementById('ticker-filter').value = '';
  updateTickerLabel();
  currentSort = 'email_time_et';
  currentOrder = 'desc';
  applySortUI();
  document.getElementById('unread-filter').classList.remove('active');
  trashView = false;
  document.getElementById('trash-view').classList.remove('active');
  savePrefs();
  search(0);
}

/* ── 휴지통 카드 복원 ── */
function restoreCard(articleId, element) {
  const card = element.closest('.card');
  if (card.dataset.restoring) return;
  card.dataset.restoring = '1';
  card.classList.add('card-deleting');

  fetch(`/api/articles/${articleId}/restore`, { method: 'POST' })
    .then(res => {
      if (res.ok) {
        card.remove();
      } else {
        card.classList.remove('card-deleting');
        delete card.dataset.restoring;
        showToast('복원 실패', null, null);
      }
    })
    .catch(() => {
      card.classList.remove('card-deleting');
      delete card.dataset.restoring;
      showToast('복원 중 오류 발생', null, null);
    });
}

document.getElementById('q').addEventListener('keydown', e => {
  if (e.key === 'Enter') search(0);
});
// Esc로 모달 닫기
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  hideTickerPopover();
  closeTickerModal();
});

/* ── Init ── */
async function init() {
  await loadFilters();             // 먼저 ticker 옵션 로드
  loadPrefs();                     // 로컬에 저장된 검색조건 기본값 적용
  const savedOffset = restoreFromURL(); // URL이 있으면 우선 (공유 링크)
  search(savedOffset);
  startNotificationPolling();
}
init();
