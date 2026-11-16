/* SA 대시보드 — 티커 표·칩 이름과 카드 그리기.
   전역 범위를 함께 쓰는 일반 스크립트다. index.html이 app.js → app-cards → app-quote → app-actions →
   app-feed → app-settings → app-boot 순서로 읽는다. */
// 동일 종목(클래스 차이) 병합 규칙 — 단일 소스는 db.TICKER_ALIASES.
// loadFilters()가 /api/filters에서 받아와 채움 (실패 시 빈 맵 = 병합 없이 원본 유지).
let TICKER_ALIASES = {};
const canonTicker = (t) => TICKER_ALIASES[t.toUpperCase()] || t;

// 외국 기업의 미국 티커(대부분 OTC ADR, 일부 NYSE ADR)를 자국 시장 티커로 매핑.
// 배지 표기와 시세 조회(quote) 모두 이 자국 티커를 사용한다.
//   byName:true → 기업명 배지 (한국·일본·중화권 종목: 삼성전자 / Sony)
//   (기본)      → 자국 티커 배지 + 마우스오버 영문 기업명 (그 외 외국 기업)
// EXTRA_LISTINGS: 동일 기업의 복수 상장 — 기본 칩은 그대로 두고 다른 시장 상장 칩을 '추가'로 노출한다
// (Ferrari RACE + 2FE.DE, TSM + 2330.TW, SKHY + 000660.KS).
// 두 표는 증류 기업 등록부에서 만든다(2026-11-11, company_table.py — 같은 회사 심볼 묶음·칩 이름은 등록부,
// 어떤 OTC를 바꾸고 어떤 칩을 더할지는 sa 규칙). loadFilters()가 /api/filters의 listings로 채운다.
let FOREIGN_LISTINGS = {};
let EXTRA_LISTINGS = {};
// 숫자 종목코드(2330.TW·688825.SS·005930.KS)는 읽기 어려워 칩에 기업명을 쓴다(2026-10-12 사용자 지시).
// 이름은 포트폴리오 표시명칭(/api/filters의 home_names) > 매핑 표의 이름 > 기사 회사명(법인 접미사 제거) 순.
let HOME_NAMES = {};
const NUMERIC_CODE_RE = /^\d[0-9A-Z]*(?:\.[A-Z]{1,3})?$/;
function shortCompany(name) {
  let n = String(name || '').trim(), prev;
  do {   // 'Holding Co., Ltd.'처럼 겹친 법인 접미사는 거듭 뗀다
    prev = n;
    n = n.replace(/,?\s+(?:Co\.,?\s*Ltd\.?|Company Limited|Corporation|Corp\.?|Inc\.?|Limited|Ltd\.?|Holdings?|Group|plc|S\.A\.|AG|N\.V\.)$/i, '').trim();
  } while (n !== prev);
  return n.length > 22 ? n.slice(0, 21) + '…' : n;
}
function codeLabel(label, quoteTicker, ...names) {
  if (!NUMERIC_CODE_RE.test(label)) return label;
  const n = HOME_NAMES[quoteTicker] || HOME_NAMES[label] || names.map(shortCompany).find(Boolean);
  return n || label;
}
// 추가 상장 티커 → 표기 정보 역인덱스 (한국 종목은 기업명 표기 관례를 따름)
let EXTRA_BY_TICKER = {};
function applyListings(listings) {
  FOREIGN_LISTINGS = (listings && listings.foreign) || {};
  EXTRA_LISTINGS = (listings && listings.extra) || {};
  EXTRA_BY_TICKER = {};
  for (const list of Object.values(EXTRA_LISTINGS)) {
    for (const ex of list) EXTRA_BY_TICKER[ex.ticker] = ex;
  }
}

function extractTickers(a) {
  // LLM이 관련성 판단해 선별한 ticker 필드만 사용
  // ($TICKER 정규식 무조건 수집은 제거 — 스치는 언급까지 배지로 붙는 문제)
  const map = new Map();
  const rawTicker = (a.ticker || '').trim();
  if (rawTicker && rawTicker.toUpperCase() !== 'NONE') {
    const tks = rawTicker.split(/[,·\s]+/).map(t => t.trim()).filter(t => /^[A-Z0-9.^-]{1,12}$/.test(t));
    const names = (a.company_name || '').split(/·/).map(n => n.trim()).filter(Boolean);
    tks.forEach((t, i) => { const c = canonTicker(t); if (c && !map.has(c)) map.set(c, names[i] || names[0] || ''); });
  }
  // 복수 상장 칩 추가. 중복 판정은 '실제 조회 티커' 기준 —
  // 예: 한 기사에 SKHY와 HXSCL이 함께 태깅되면 HXSCL이 이미 000660.KS로
  //     조회되므로 SKHY의 추가 칩(000660.KS)은 붙이지 않는다.
  const covered = new Set();
  for (const t of map.keys()) {
    const fl = FOREIGN_LISTINGS[t];
    covered.add(fl ? fl.home : t);
  }
  for (const t of [...map.keys()]) {   // 순회 중 변경 방지를 위해 키 스냅샷
    for (const ex of (EXTRA_LISTINGS[t] || [])) {
      if (covered.has(ex.ticker) || map.has(ex.ticker)) continue;
      map.set(ex.ticker, ex.name || '');
      covered.add(ex.ticker);
    }
  }
  return [...map.entries()].map(([ticker, name]) => ({ ticker, name }));
}

// parse_method(db) → 카드에 표기할 수집방식 라벨. NULL(기존행)이면 빈값.
function parseMethodLabel(m) {
  if (!m) return '';
  if (m.startsWith('sa_api')) return 'SA API';
  if (m.startsWith('jina')) return 'Jina';
  if (m.startsWith('playwright')) return 'Playwright';
  if (m.startsWith('curl_cffi')) return 'curl';
  if (m === 'grok_partial') return 'Grok Bot(일부)';   // Grok Bot이 드라이브로 넘긴 원문(2026-10-11)
  if (m.startsWith('grok')) return 'Grok Bot';
  return m;
}

/* ── Card Render ── */
function renderCard(a) {
  const articleId = Number(a.id) || 0;
  const details = (Array.isArray(a.summary_details) ? a.summary_details : [])
    .map(detail => `<li>${escapeHTML(detail)}</li>`).join('');
  const timeLabel = escapeHTML(formatTime(a.email_time_et));
  // 화면 번호는 DB 기사 ID(articles.id). 예전엔 메일 ID(email_id)를 '기사 ID'라며 보였다
  // (2026-10-08 사용자 지적 — 9364는 메일 ID, 기사 ID는 8885). 메일 ID는 툴팁에 남긴다.
  const emailIdLabel = articleId
    ? `<button type="button" class="article-id" data-article-id="${articleId}" `
      + `onclick="copyArticleId(this)" title="기사 ID 복사${a.email_id ? ` (메일 ID ${escapeAttr(a.email_id)})` : ''}">ID:${articleId}</button>`
    : '';
  const footerMeta = [emailIdLabel, timeLabel].filter(Boolean).join(' · ');
  const methodLabel = escapeHTML(parseMethodLabel(a.parse_method));
  const modelLabel = escapeHTML(summaryModelLabel(a.summary_model));
  const metaLine2 = [methodLabel, modelLabel].filter(Boolean).join(' · ');
  const isRead = !!a.is_read;
  const unreadDot = !isRead ? '<span class="unread-dot" title="미읽음"></span>' : '';
  const readBtnClass = isRead ? 'read-btn done' : 'read-btn';
  const readBtnTitle = isRead ? '읽음 취소' : '읽음 처리';
  const hasOrig = !!a.original_title;
  const originalTitle = hasOrig ? `<div class="card-orig-title">${escapeHTML(a.original_title)}</div>` : '';

  const tickers = extractTickers(a);
  const tickerBadges = tickers.map((t, i) => {
    const color = i === 0 ? (a.ticker_color || 'blue') : 'gray';
    const fl = FOREIGN_LISTINGS[t.ticker];
    let label, companyName, quoteTicker;
    if (fl && fl.byName)   { label = fl.name; companyName = fl.name; quoteTicker = fl.home; }
    else if (fl)       { label = codeLabel(fl.home, fl.home, fl.name, t.name); companyName = fl.name || t.name; quoteTicker = fl.home; }
    else {
      // 추가 상장 칩 중 byName 지정분(한국 등)은 기업명으로 표기
      const ex = EXTRA_BY_TICKER[t.ticker];
      label = (ex && ex.byName && ex.name) ? ex.name : codeLabel(t.ticker, t.ticker, ex && ex.name, t.name);
      companyName = t.name || t.ticker;
      quoteTicker = t.ticker;
    }
    const attrs = [
      `data-ticker="${escapeAttr(t.ticker)}"`,
      `data-quote-ticker="${escapeAttr(quoteTicker)}"`,
      `data-company="${escapeAttr(companyName || '')}"`,
      'role="button"',
      'tabindex="0"',
    ].join(' ');
    return `<span class="ticker-badge ticker-${color} ticker-live" ${attrs}>${escapeHTML(label)}</span>`;
  }).join('');

  // 키워드 태그는 표시하지 않음 — 티커 배지만 사용
  const combinedBadges = tickerBadges;

  // 모바일 스와이프 배경 (telegram-digest 이식) — PC는 @media(hover:hover)에서 숨김
  const swipeEye = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;

  return `
<div class="swipe-row">
  <div class="swipe-action left" aria-hidden="true">${swipeEye}<span>읽음</span></div>
  <div class="swipe-action right" aria-hidden="true"><span>읽음</span>${swipeEye}</div>
<div class="card${!isRead ? ' card-unread' : ''}" data-id="${articleId}" data-read="${isRead ? '1' : '0'}" style="--accent:${ACCENT[a.ticker_color] || ACCENT.blue}">
  <div class="card-title-row">
    ${unreadDot}
    <div class="card-heading">
      <h2 class="card-title">${escapeHTML(a.headline)}</h2>
      ${originalTitle}
    </div>
  </div>
  <hr class="card-divider">
  <div class="card-details">
    <ul>${details}</ul>
  </div>
  ${combinedBadges ? `<div class="card-tickers">${combinedBadges}</div>` : ''}
  <div class="card-footer">
    <span class="footer-left">${footerMeta}${metaLine2 ? `<span class="footer-method">${metaLine2}</span>` : ''}</span>
    <div class="footer-actions">
      ${trashView ? '' : `<button class="${readBtnClass}" onclick="toggleRead(${articleId}, this)" title="${readBtnTitle}">${isRead ? SVG_EYE_OFF : SVG_EYE}</button>`}
      <a class="link-btn" href="${escapeAttr(safeExternalURL(a.article_url))}" target="_blank" rel="noopener noreferrer">원문보기</a>
      ${trashView
        ? `<button class="restore-btn" onclick="restoreCard(${articleId}, this)" title="복원">${SVG_RESTORE}복원</button>`
        : `<button class="delete-btn" onclick="deleteCard(${articleId}, this)" title="삭제">${SVG_TRASH}</button>`}
    </div>
  </div>
</div>
</div>`;
}
