/* SA 대시보드 — 티커칩 시세 팝오버.
   전역 범위를 함께 쓰는 일반 스크립트다. index.html이 app.js → app-cards → app-quote → app-actions →
   app-feed → app-settings → app-boot 순서로 읽는다. */
/* ── Ticker popover: company + portfolio v2 live change ── */
const quoteCache = new Map(); // quoteTicker → { at, data } | { at, error }
const QUOTE_TTL_MS = 60_000;

/* ── 포트폴리오(8765) 종목 상세 딥링크 ──
   같은 머신의 다른 포트라 현재 호스트를 그대로 재사용한다(localhost/Tailscale 양쪽 동작).
   포트폴리오 서버는 http만 서빙하므로 스킴은 http 고정. */
const PORTFOLIO_WEB_PORT = 8765;

function portfolioChartHref(ticker) {
  const t = String(ticker || '').trim().toUpperCase();
  const host = location.hostname;
  if (!t || !host) return '';
  return `http://${host}:${PORTFOLIO_WEB_PORT}/#chart=${encodeURIComponent(t)}`;
}

/* 시세가 확인된 종목만 링크로 만든다 — 값이 없으면 상세화면도 빈 차트라 링크 의미가 없다. */
function setTickerPopoverLink(el, ticker) {
  const link = el.querySelector('.tqp-name');
  if (!link) return;
  const href = portfolioChartHref(ticker);
  if (href) {
    link.href = href;
    link.title = '포트폴리오에서 이 종목 보기';
  } else {
    link.removeAttribute('href');
    link.removeAttribute('title');
  }
}

/* 전광판 지표(2026-11-07 사용자 지시, wm·sa·td 공통): 포트폴리오가 계산한 일·주·월 RSI·BB(%B)를
   'RSI 58-61-70' 형식(일-주-월, 정수)으로, 최근 1주·1개월·3개월 등락률을 한 줄씩. 값이 없으면 숨긴다. */
function renderQuoteStats(el, d) {
    const box = el.querySelector('.tqp-stats');
    if (!box) return;
    const s = d && d.quote_stats;
    // 값마다 색(포트폴리오 관례: 50 위 빨강·아래 파랑, RSI ±20·BB ±50에서 가장 진함), 구분자는 가운데 점 '·', 음수는 '−'(U+2212)
    const tone = (v, span) => { const t = Math.min(1, Math.abs(v - 50) / span); return `${v >= 50 ? 'up' : 'down'}" style="opacity:${(0.5 + 0.5 * t).toFixed(2)}`; };
    const tri = (g, span) => (g && ['day', 'week', 'month'].some((k) => g[k] != null))
        ? ['day', 'week', 'month'].map((k) => {
            if (g[k] == null) return '<span class="tqp-iv flat">–</span>';
            const r = Math.round(g[k]);
            return `<span class="tqp-iv ${tone(r, span)}">${r < 0 ? '−' + Math.abs(r) : r}</span>`;
        }).join('<span class="tqp-sep">·</span>') : '';
    const rsi = s ? tri(s.rsi, 20) : '', bb = s ? tri(s.bollinger_pband, 50) : '';
    const perf = (s && s.performance) || {};
    // 1W·1M만, 소수 1자리(2026-11-07 사용자 지시로 3M·YTD는 뺐다 — API에는 남아 있다)
    const pct = (v, dp) => { const x = Number(v.toFixed(dp)); return { text: (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(dp) + '%', cls: x > 0 ? 'up' : x < 0 ? 'down' : 'flat' }; };
    const cells = [['one_week', '1W', 1], ['one_month', '1M', 1]]
        .filter(([k]) => perf[k] != null)
        .map(([k, label, dp]) => { const c = pct(perf[k], dp); return `<span class="tqp-perf"><span class="tqp-perf-label">${label}</span><span class="tqp-perf-chg ${c.cls}">${c.text}</span></span>`; });
    if (!rsi && !bb && !cells.length) { box.hidden = true; box.innerHTML = ''; return; }
    // RSI·BB 각각 한 줄, 라벨은 오른쪽 정렬·세 값은 두 줄이 위아래로 맞게 한 격자에 둔다(2026-11-07)
    const ind = [rsi ? `<div class="tqp-ind"><span class="tqp-ind-label">RSI</span>${rsi}</div>` : '', bb ? `<div class="tqp-ind"><span class="tqp-ind-label">BB</span>${bb}</div>` : ''].join('');
    box.innerHTML = (ind ? `<div class="tqp-inds">${ind}</div>` : '') + (cells.length ? `<div class="tqp-perfs">${cells.join('')}</div>` : '');
    box.hidden = false;
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
      <a class="tqp-name" target="_blank" rel="noopener noreferrer"></a>
    </div>
    <div class="tqp-body">
      <span class="tqp-price">…</span>
      <span class="tqp-chg flat">…</span>
    </div>
    <div class="tqp-ext" hidden><span class="tqp-ext-label"></span><span class="tqp-ext-chg flat"></span></div>
    <div class="tqp-stats" hidden></div>
    <div class="tqp-meta"></div>`;
  // 새 탭으로 열리므로 남아 있는 팝오버는 정리한다
  el.querySelector('.tqp-name').addEventListener('click', (e) => {
    if (!e.currentTarget.getAttribute('href')) { e.preventDefault(); return; }
    hideTickerPopover();
  });
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

  setTickerPopoverLink(el, (d && d.current_price != null) ? (d.ticker || quoteTicker) : '');

  if (!d || d.found === false || d.current_price == null) {
    price.textContent = '시세 없음';
    chg.textContent = '';
    chg.className = 'tqp-chg flat';
    meta.textContent = packed.error ? '포트폴리오 서버 연결 실패' : '포트폴리오 시세 미제공';
    renderQuoteStats(el, null);
    return;
  }
  price.textContent = fmtPrice(d.current_price, d.currency);
  const { text, cls } = fmtChangePct(d.change_pct);
  chg.textContent = text;
  chg.className = `tqp-chg ${cls}`;
  // 장외 상태값(PRE/POST 등)과 정규장 종가 대비 등락을 병기한다.
  const hasExtendedState = isExtendedMarketState(d.extended_market_state);
  if (hasExtendedState || (!d.extended_market_state && d.extended_change_pct != null)) {
    extLabel.textContent = formatExtendedMarketState(d.extended_market_state, d.market_label);
    if (d.extended_change_pct != null) {
      const e = fmtChangePct(d.extended_change_pct);
      extChg.textContent = e.text;
      extChg.className = `tqp-ext-chg ${e.cls}`;
    } else {
      extChg.textContent = '';
      extChg.className = 'tqp-ext-chg flat';
    }
    ext.hidden = false;
  }
  renderQuoteStats(el, d);
  meta.textContent = '';
}

async function showTickerQuote(badge) {
  const quoteTicker = (badge.dataset.quoteTicker || badge.dataset.ticker || '').toUpperCase();
  const company = badge.dataset.company || '';
  if (!quoteTicker) return;
  const el = ensureTickerPopover();
  el.dataset.activeTicker = quoteTicker;
  // loading state
  el.querySelector('.tqp-name').textContent = company || nameCache[quoteTicker] || quoteTicker;
  setTickerPopoverLink(el, '');
  el.querySelector('.tqp-price').textContent = '불러오는 중…';
  el.querySelector('.tqp-chg').textContent = '';
  el.querySelector('.tqp-chg').className = 'tqp-chg flat';
  el.querySelector('.tqp-ext').hidden = true;
  renderQuoteStats(el, null);
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
