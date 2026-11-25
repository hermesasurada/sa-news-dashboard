/* SA 대시보드 — 목록 불러오기 — 무한 스크롤·페이지·주소 동기화·새 기사 알림·검색·휴지통.
   전역 범위를 함께 쓰는 일반 스크립트다. index.html이 app.js → app-cards → app-quote → app-actions →
   app-feed → app-settings → app-boot 순서로 읽는다. */
/* ── 모바일 무한 스크롤(2026-10-20 사용자 지시, wm과 같은 방식) ──
   폭 640px 이하는 페이지 버튼 대신 목록 끝이 화면 아래 600px 안에 들어오면 다음 묶음을 이어 붙인다.
   다음 시작 위치는 '지금 화면에 남은 카드 수'로 정한다 — 읽음·삭제로 카드가 빠지면 서버 목록이
   당겨지므로 저장된 페이지 번호로 받으면 그만큼 건너뛴다. 겹친 카드는 data-id로 거른다. */
const _isMobileList = () => window.matchMedia('(max-width: 640px)').matches;
const _feed = { loading: false, done: false, seq: 0 };
function _nearListEnd() {
  const pag = document.getElementById('pagination');
  return !!pag && pag.getBoundingClientRect().top < window.innerHeight + 600;
}
async function loadMoreArticles() {
  if (!_isMobileList() || _feed.loading || _feed.done || currentListTotal === null) return;
  const cardsEl = document.getElementById('cards');
  const shown = cardsEl.querySelectorAll('.card').length;
  if (!shown || shown >= currentListTotal) { _feed.done = true; renderPagination(currentListTotal, currentOffset); return; }
  _feed.loading = true;
  const seq = _feed.seq;
  const params = getParams(currentOffset + shown);
  params.set('include_total', 'false');
  params.set('include_queue', 'false');
  try {
    const data = await fetchJSON('/api/articles?' + params.toString());
    if (seq !== _feed.seq) return;                       // 그사이 검색·필터가 바뀌었다
    const have = new Set([...cardsEl.querySelectorAll('.card[data-id]')].map(c => c.dataset.id));
    const fresh = (data.items || []).filter(a => !have.has(String(Number(a.id) || 0)));
    if (!data.items || !data.items.length) _feed.done = true;
    if (fresh.length) {
      cardsEl.insertAdjacentHTML('beforeend', fresh.map(renderCard).join(''));
      attachSwipeHandlers();
      attachTickerQuoteHandlers();
    }
    const now = cardsEl.querySelectorAll('.card').length;
    if (now >= currentListTotal) _feed.done = true;
  } catch (e) {
    console.error('다음 기사 불러오기 실패', e);
  } finally {
    if (seq === _feed.seq) {
      _feed.loading = false;
      renderPagination(currentListTotal, currentOffset);
      if (!_feed.done && _nearListEnd()) setTimeout(loadMoreArticles, 0);   // 붙인 뒤에도 끝이 보이면 이어서
    }
  }
}
(function setupInfiniteScroll() {
  const pag = document.getElementById('pagination');
  if (pag && 'IntersectionObserver' in window) {
    new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) loadMoreArticles(); },
                             { rootMargin: '0px 0px 600px 0px' }).observe(pag);
  }
  window.addEventListener('scroll', () => { if (_nearListEnd()) loadMoreArticles(); }, { passive: true });
})();

/* ── Pagination ── */
function renderPagination(total, offset) {
  const pag = document.getElementById('pagination');
  if (_isMobileList()) {                                  // 모바일: 페이지 버튼 대신 진행 표시
    const shown = document.getElementById('cards').querySelectorAll('.card').length;
    pag.innerHTML = !total || !shown ? ''
      : `<span class="page-info">${(_feed.done || offset + shown >= total)
          ? `${offset + shown}건 · 끝` : `${offset + shown}/${total}건 · ${_feed.loading ? '불러오는 중…' : '내리면 더 불러옵니다'}`}</span>`;
    return;
  }
  const size = pageSize();
  const totalPages = Math.ceil(total / size);
  const currentPage = Math.floor(offset / size);
  if (totalPages <= 1) { pag.innerHTML = ''; return; }

  let html = `<button onclick="search(${(currentPage-1)*size}, false)" ${currentPage===0?'disabled':''}>◀ 이전</button>`;
  // 한 번에 최대 10개씩 블록 단위로 노출 (1~10, 11~20 …)
  const BLOCK = 10;
  const start = Math.floor(currentPage / BLOCK) * BLOCK;
  const end = Math.min(totalPages - 1, start + BLOCK - 1);
  for (let i = start; i <= end; i++) {
    html += `<button class="${i===currentPage?'active':''}" onclick="search(${i*size}, false)">${i+1}</button>`;
  }
  html += `<button onclick="search(${(currentPage+1)*size}, false)" ${currentPage===totalPages-1?'disabled':''}>다음 ▶</button>`;
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
  if (sp.has('unread_only')) document.getElementById('unread-filter').classList.add('active');
  // URL이 정렬을 지정하면 로컬 기본값보다 우선 (공유 링크)
  if (sp.has('order'))   currentOrder = sp.get('order') === 'asc' ? 'asc' : 'desc';
  applySortUI();
  const offset = parseInt(sp.get('offset') || '0') || 0;
  return offset - offset % pageSize();   // 보기 방식마다 페이지 크기가 달라 페이지 경계에 맞춘다
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
      const { total } = await fetchJSON('/api/articles/state');
      if (total > lastKnownTotal) {
        showNewArticlesBanner(total - lastKnownTotal);
      }
    } catch(e) {}
  }, 5 * 60 * 1000);
}

/* ── Search ── */
// 큐 표시 — 안읽음 건수는 눈 아이콘(미읽음만) 버튼 안(2026-10-01), Grok 대기 줄은 검색줄 아래(2026-11-25).
// 결과 건수 줄·대기·실패 건수는 2026-11-25 사용자 지시로 삭제했다.
function renderQueue(qData) {
  const el = document.getElementById('unread-count');
  if (el) {
    const n = (qData && qData.unread) || 0;
    el.textContent = n;
    el.hidden = trashView || n <= 0;
  }
  // Grok Bot 모드일 때만 서버가 queue.grok을 준다 — 원문을 요청하고 기다리는 건수와,
  // 원문이 들어와 요약을 기다리는 건수(2026-11-25 사용자 지시)
  const gw = document.getElementById('grok-wait');
  if (gw) {
    const g = qData && qData.grok;
    gw.hidden = trashView || !g;
    if (g) {   // '원문 대기 3건 (마지막 11-25 19:40) · 요약 대기 0건' — 건수는 티커 칩 모양
      const n = (v) => `<span class="ticker-badge">${Number(v) || 0}</span>`;
      const last = g.waiting > 0 && g.latest ? ` (마지막 ${escapeHTML(String(g.latest).slice(5, 16).replace('T', ' '))})` : '';
      gw.innerHTML = `원문 대기 ${n(g.waiting)}건${last} · 요약 대기 ${n(g.summarizing)}건`;
    }
  }
}

function adjustCurrentListMeta(totalDelta = 0, unreadDelta = 0) {
  if (currentListTotal !== null) {
    currentListTotal = Math.max(0, currentListTotal + totalDelta);
  }
  currentQueue = {
    ...currentQueue,
    unread: Math.max(0, currentQueue.unread + unreadDelta),
  };
  renderQueue(currentQueue);   // 안읽음 건수는 바로 다시 그린다(읽음·삭제 즉시 반영)
}

function renderCurrentListMeta() {
  if (currentListTotal === null) return;
  renderQueue(currentQueue);
  renderPagination(currentListTotal, currentOffset);
}

/* ── 카드 1건이 빠진 자리를 다음 기사로 자동 보충 ──
   삭제·복원·(미읽음 필터에서의)읽음처리로 카드가 사라져도 페이지가 비지 않도록,
   전체 재렌더 없이 서버에서 다음 순번 1건만 가져와 뒤에 덧붙인다. */
async function refillGrid() {
  const cardsEl = document.getElementById('cards');
  const shown = cardsEl.querySelectorAll('.card').length;
  if (shown >= pageSize()) return;   // 이미 가득 참
  const params = getParams(currentOffset + shown);
  params.set('limit', 1);
  params.set('include_total', 'false');
  params.set('include_queue', 'false');
  try {
    const data = await fetchJSON('/api/articles?' + params.toString());
    renderPagination(currentListTotal, currentOffset);
    if (!data.items.length) return;   // 마지막 페이지 — 보충할 기사 없음
    cardsEl.insertAdjacentHTML('beforeend', renderCard(data.items[0]));
    attachSwipeHandlers();
    attachTickerQuoteHandlers();
  } catch (e) {
    console.error('카드 보충 실패', e);
  }
}

async function search(offset = 0, refreshMeta = true) {
  currentOffset = offset;
  _feed.seq++; _feed.loading = false; _feed.done = false;   // 이어 받기 상태 초기화(늦게 온 응답은 버린다)
  const params = getParams(offset);

  // #9: URL 동기화
  syncURL(params);
  if (!refreshMeta && currentListTotal !== null) {
    params.set('include_total', 'false');
    params.set('include_queue', 'false');
  }

  const cardsEl = document.getElementById('cards');
  cardsEl.innerHTML = '<div class="empty-state">불러오는 중...</div>';

  try {
    const data = await fetchJSON('/api/articles?' + params.toString());
    if (typeof data.total === 'number') currentListTotal = data.total;
    if (data.queue) currentQueue = data.queue;

    renderQueue(currentQueue);

    if (data.items.length === 0) {
      const hasFilter = !!(document.getElementById('q').value.trim()
        || document.getElementById('unread-filter').classList.contains('active'));
      let msg, icon;
      if (trashView)       { icon = '🗑'; msg = '휴지통이 비어있습니다.'; }
      else if (hasFilter)  { icon = '🔍'; msg = '조건에 해당하는 기사가 없습니다.'; }
      else                 { icon = '📭'; msg = '표시할 기사가 없습니다.'; }
      cardsEl.innerHTML = `<div class="empty-state"><span class="empty-icon">${icon}</span>${msg}</div>`;
      document.getElementById('pagination').innerHTML = '';
      return;
    }

    cardsEl.innerHTML = data.items.map(renderCard).join('');
    attachSwipeHandlers();
    attachTickerQuoteHandlers();
    renderPagination(currentListTotal, offset);

    // #7: 필터 없는 1페이지 결과로 기준 total 갱신
    const qVal = document.getElementById('q').value.trim();
    const uVal = document.getElementById('unread-filter').classList.contains('active');
    if (!qVal && !uVal && offset === 0) {
      lastKnownTotal = currentListTotal;
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
        adjustCurrentListMeta(-1, 0);
        (card.closest('.swipe-row') || card).remove();
        refillGrid();
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
  closeModelConfig();
});
