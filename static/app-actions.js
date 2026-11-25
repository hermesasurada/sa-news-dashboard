/* SA 대시보드 — 스와이프·읽음·삭제·되돌리기·토스트.
   전역 범위를 함께 쓰는 일반 스크립트다. index.html이 app.js → app-cards → app-quote → app-actions →
   app-feed → app-settings → app-boot 순서로 읽는다. */
/* ── 모바일 스와이프 → 읽음처리 (telegram-digest 이식) ──
   터치 이벤트만 사용 → 데스크톱 무영향. 좌/우 양방향, 미읽음 카드만. */
const SWIPE_INTERACTIVE = '.read-btn,.link-btn,.delete-btn,.restore-btn,.ticker-badge,a,button';

function attachSwipeHandlers() {
  if (trashView) return;  // 휴지통 뷰: 스와이프 없음 (read-btn 부재)
  document.querySelectorAll('.swipe-row').forEach((row) => {
    if (row.dataset.swipeBound) return;   // 보충 렌더 시 리스너 중복 누적 방지
    row.dataset.swipeBound = '1';
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
    // 브라우저가 터치를 가져가면(touchcancel) 밀던 카드를 제자리로 — 없으면 카드가 밀린 채 남고 다음 터치가 꼬인다.
    row.addEventListener('touchcancel', () => {
      if (!active) return;
      active = false; axis = null; dx = 0;
      reset(true); unswipe();
    });
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
const READ_FADE_MS = 160;

// 카드의 읽음 표시(dot·테두리·버튼 아이콘)를 즉시 반영. 낙관적 갱신과 실패 원복에 공용.
function applyReadState(card, btn, read) {
  card.dataset.read = read ? '1' : '0';
  card.classList.toggle('card-unread', !read);
  const dot = card.querySelector('.unread-dot');
  if (read) {
    if (dot) dot.remove();
  } else if (!dot) {
    const titleRow = card.querySelector('.card-title-row');
    if (titleRow) titleRow.insertAdjacentHTML('afterbegin', '<span class="unread-dot" title="미읽음"></span>');
  }
  if (btn) {
    btn.className = read ? 'read-btn done' : 'read-btn';
    btn.title = read ? '읽음 취소' : '읽음 처리';
    btn.innerHTML = read ? SVG_EYE_OFF : SVG_EYE;
  }
}

async function toggleRead(id, btn) {
  const card = btn.closest('.card');
  const wasRead = card.dataset.read === '1';
  const newRead = !wasRead;
  const removeFromUnread = newRead
    && document.getElementById('unread-filter').classList.contains('active');
  const row = card.closest('.swipe-row') || card;
  let removalFrame = null;
  let removalTimer = null;
  let finishRemoval = null;
  let removalDone = Promise.resolve();

  // 낙관적 갱신 — 서버 왕복을 기다리지 않고 먼저 반영한다.
  // (기존에는 응답 후에야 아이콘이 바뀌어, 모바일/Tailscale의 RTT가 그대로 체감 지연이 됐다)
  applyReadState(card, btn, newRead);
  adjustCurrentListMeta(removeFromUnread ? -1 : 0, newRead ? -1 : 1);   // 안읽음 건수도 응답 전에 반영
  if (removeFromUnread) {
    removalDone = new Promise(resolve => {
      finishRemoval = resolve;
      row.style.transition = `opacity ${READ_FADE_MS}ms`;
      removalFrame = requestAnimationFrame(() => { row.style.opacity = '0'; });
      removalTimer = setTimeout(() => {
        row.remove();
        resolve();
      }, READ_FADE_MS);
    });
  }

  let ok = false;
  try {
    const res = await fetch(`/api/articles/${id}/read`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({is_read: newRead}),
    });
    ok = res.ok;
  } catch (e) {
    console.error('읽음 상태 변경 실패', e);
  }

  if (!ok) {
    adjustCurrentListMeta(removeFromUnread ? 1 : 0, newRead ? 1 : -1);   // 건수 원복
    if (removalFrame !== null) cancelAnimationFrame(removalFrame);
    if (removalTimer !== null) clearTimeout(removalTimer);
    if (finishRemoval) finishRemoval();
    if (row.isConnected) {
      row.style.transition = '';
      row.style.opacity = '';
      applyReadState(card, btn, wasRead);
    } else {
      search(currentOffset);
    }
    showToast('읽음 상태 변경 실패', null, null);
    return;
  }

  // 페이드는 요청과 동시에 진행했으므로 성공 응답 뒤 추가 대기가 없다.
  if (removeFromUnread) {
    // 안읽음만 보기에서는 카드가 사라져 버튼으로 되돌릴 수 없다 — 삭제와 같은 토스트로
    // 복원 기회를 준다(스와이프 읽음도 여기로 온다. wm과 같은 방식, 2026-10-09 사용자 지시).
    showToast('읽음 처리했습니다', '되돌리기', () => undoRead(id), READ_UNDO_DURATION_MS);
    await removalDone;
    refillGrid();
  } else {
    renderCurrentListMeta();
  }
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
        adjustCurrentListMeta(-1, card.dataset.read === '0' ? -1 : 0);
        // .card만 지우면 .swipe-row 래퍼가 빈 그리드 칸으로 남는다 → 래퍼째 제거 후 보충
        (card.closest('.swipe-row') || card).remove();
        refillGrid();
        // 확인창 없이 즉시 삭제하고, 하단 토스트에서만 복원 기회를 제공한다.
        showToast(
          '기사를 삭제했습니다',
          '되돌리기',
          () => undoDelete(articleId),
          DELETE_UNDO_DURATION_MS,
        );
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

/* ── 읽음 취소(안읽음 목록에서 사라진 카드 되살리기) ── */
async function undoRead(articleId) {
  try {
    const res = await fetch(`/api/articles/${articleId}/read`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({is_read: false}),
    });
    if (!res.ok) throw new Error('http ' + res.status);
    search(currentOffset);  // 목록·안읽음 수 새로고침 → 카드가 다시 나타난다
  } catch (e) {
    showToast('되돌리기 실패: ' + e.message, null, null);
  }
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
  toast.innerHTML = `<span>${escapeHTML(message)}</span>`
    + (actionLabel ? `<button type="button" class="toast-action" onclick="toastAction()">${escapeHTML(actionLabel)}</button>` : '');
  toast.classList.add('show');
  _toastTimer = setTimeout(() => {
    toast.classList.remove('show');
    _toastUndoFn = null;
    _toastTimer = null;
  }, duration);
}

function toastAction() {
  const action = _toastUndoFn;
  _toastUndoFn = null;  // 모바일 더블탭으로 복원 요청이 중복되는 것을 방지
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = null;
  document.getElementById('toast').classList.remove('show');
  if (action) action();
}
