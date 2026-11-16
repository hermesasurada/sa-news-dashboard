/* SA 대시보드 — 설정 창 — 요약 글꼴·글자 크기·요약 모델.
   전역 범위를 함께 쓰는 일반 스크립트다. index.html이 app.js → app-cards → app-quote → app-actions →
   app-feed → app-settings → app-boot 순서로 읽는다. */
/* ── 요약 본문 글꼴 선택 (website-monitor 이식) ──
   설정 창(⚙️) 안 '요약 본문 글꼴' 절에서 고른다(2026-09-30, 별도 버튼·모달 폐지).
   상태 = localStorage 'saReaderFont'. body[data-reader-font]로 카드 요약 본문
   (.card-details/.card-summary)에 적용. */
// 글꼴 목록·글꼴 값은 공용 hermes-reader-fonts/fonts.js가 정본(2026-11-01 사용자 지시) — 공용 목록에 글꼴을 더하면
// 여기 고칠 것 없이 나타난다. 옛 저장값 'sans'는 Pretendard였다. 목록에 없는 값(지운 글꼴)은 기본값으로.
const _RF = window.HermesReaderFonts
  || {list: [], get: () => null, resolve: () => null, apply() {}, fillSelect() {}, ensureWeb() {}};
let _readerFont = _RF.resolve(localStorage.getItem('saReaderFont'), {legacy: {sans: 'pretendard'}, fallback: 'pretendard'});

function applyReaderFont() {
  _RF.apply(document.body, _readerFont);
}
function setReaderFont(key) {
  if (!_RF.get(key)) return;
  _readerFont = key;
  localStorage.setItem('saReaderFont', key);
  applyReaderFont();
  if (document.getElementById('model-modal').classList.contains('show')) renderFontList();
}
function renderFontList() {
  document.getElementById('font-list').innerHTML = _RF.list.map(f => `
    <button type="button" class="font-opt ${f.id === _readerFont ? 'sel' : ''}" onclick="setReaderFont('${escapeHTML(f.id)}')">
      <span>${escapeHTML(f.label)}</span>
      <span class="fo-sample" style="font-family:${escapeHTML(f.stack)}">본문 가나다 AaBb</span>
      ${f.id === _readerFont ? '<span class="fo-check">✓</span>' : ''}
    </button>`).join('');
}

/* ── 요약 본문 글자 크기(2026-11-05 사용자 지시, xw와 같은 방식) ──
   상태 = localStorage 'saReaderSize'(xw와 같은 12~17, 기본 13). body --reader-scale(값/13)을 hermes-ui.css의
   기본 12.75px에 곱하므로 기본 화면은 그대로이고 .card-details/.card-summary만 바뀐다. */
const SIZE_BASE = 13, SIZES = [12, 13, 14, 15, 16, 17];
let _readerSize = Number((() => { try { return localStorage.getItem('saReaderSize'); } catch (e) { return null; } })());
if (!SIZES.includes(_readerSize)) _readerSize = SIZE_BASE;

function applyReaderSize() {
  document.body.style.setProperty('--reader-scale', String(_readerSize / SIZE_BASE));
}
function setReaderSize(px) {
  if (!SIZES.includes(px)) return;
  _readerSize = px;
  try { localStorage.setItem('saReaderSize', String(px)); } catch (e) {}
  applyReaderSize();
  renderSizeSeg();
}
function renderSizeSeg() {
  document.getElementById('size-seg').innerHTML = SIZES.map(px =>
    `<button type="button" role="radio" aria-checked="${px === _readerSize}" onclick="setReaderSize(${px})">${px}</button>`).join('');
}

/* ── 요약 모델 설정(wm 설정 팝업 이식, 2026-09-26) ─────────────────────────────
   화면은 공통 ModelSelector(슬롯 모드, 2026-10-12 — wm·yt와 같은 방식)가 그리고 여기서는
   상태·저장만 맡는다. 모델 목록은 서버가 공용 LLM 카탈로그에서 준다(Claude·GPT·Grok).
   슬롯: 칸마다 모델+추론, 1~5칸, 같은 모델 여러 칸 가능. 라운드로빈: 기사마다 시작 칸을
   돌려 나눠 맡고, 실패하면 나머지 모델이 한 번씩 받는다. */
const MC_LIMITS = { min: 1, max: 5 };
let _mc = null;
let _mcStatus = '';

function _mcState() {
  return {
    slots: _mc.config.slots, nextIndex: null, limits: MC_LIMITS,
    versions: (_mc.model_options || []).map(v => ({ ...v, slot: v.provider })),
    efforts: _mc.reasoning_options || [],
    tag: '라운드로빈',
    hint: '기사마다 시작 슬롯이 돌아가며 요약하고, 실패하면 나머지 모델이 받는다. 같은 모델을 여러 칸에 두면 그만큼 자주 먼저 쓰인다.',
    status: _mcStatus,
    notes: [],
  };
}

function renderModelConfig() {
  const root = document.getElementById('model-selector');
  const slots = _mc.config.slots;
  const options = _mc.model_options || [];
  ModelSelector.render(root, _mcState(), {
    onSlotModel(i, value) {
      saveModelConfig(() => {
        const option = options.find(o => o.value === value);
        const previous = slots[i];
        const effort = option && option.reasoning && !option.reasoning.includes(previous.effort) ? 'default' : previous.effort;
        slots[i] = { ...previous, model: value, effort };
        if (effort !== previous.effort) _mcStatus = '모델에 맞게 추론 수준을 기본값으로 변경했습니다';
      });
    },
    onSlotEffort(i, value) {
      saveModelConfig(() => { slots[i] = { ...slots[i], effort: value }; });
    },
    onAddSlot() {
      if (slots.length >= MC_LIMITS.max) return;
      // 아직 안 쓴 모델을 먼저 제안한다(다 쓰였으면 첫 모델).
      const used = new Set(slots.map(x => x.model));
      const fresh = options.find(o => o.enabled !== false && !used.has(o.value)) || options.find(o => o.enabled !== false);
      if (!fresh) return;
      saveModelConfig(() => { slots.push({ model: fresh.value, effort: 'default' }); });
    },
    onRemoveSlot(i) {
      if (slots.length <= MC_LIMITS.min) return;
      saveModelConfig(() => { slots.splice(i, 1); });
    },
  });
}

async function openModelConfig() {
  ensureReaderWebFonts();          // 글꼴 견본을 제 글꼴로 보여 주려면 웹폰트가 필요하다
  renderFontList();
  renderSizeSeg();
  document.getElementById('model-modal').classList.add('show');
  try {
    _mc = await fetchJSON('/api/summary-config');
    _mcConfirmed = JSON.stringify(_mc.config);
    _mcStatus = '';
    renderModelConfig();
  } catch (e) {
    document.getElementById('model-selector').textContent = '설정을 불러오지 못했습니다';
  }
}
function closeModelConfig() {
  document.getElementById('model-modal').classList.remove('show');
}

/*
 * 변경을 적용하고 바로 저장한다. 저장은 한 줄로 세워 차례로 보내고, 뒤에 더 새 변경이
 * 줄 서 있으면 앞 요청의 응답으로 화면을 덮지 않는다(연달아 바꾸면 늦게 온 옛 응답이
 * 화면을 되돌리던 문제, Astra 검토 2026-09-26). 실패하면 서버가 마지막으로 확인한
 * 상태로 되돌린다.
 */
let _mcSaveSeq = 0;
let _mcSaveChain = Promise.resolve();
let _mcConfirmed = null;           // 서버가 마지막으로 확인한 config

function saveModelConfig(mutate) {
  if (_mcConfirmed === null) _mcConfirmed = JSON.stringify(_mc.config);
  _mcStatus = '';
  mutate();
  const adjusted = _mcStatus;
  const seq = ++_mcSaveSeq;
  _mcStatus = '저장 중…';
  renderModelConfig();
  const job = _mcSaveChain.then(async () => {
    if (seq !== _mcSaveSeq) return;          // 뒤의 요청이 최신 상태를 통째로 보낸다
    try {
      const r = await fetch('/api/summary-config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slots: _mc.config.slots }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      _mcConfirmed = JSON.stringify(d.config);
      if (seq !== _mcSaveSeq) return;        // 기다리는 사이 새 변경이 생겼다
      _mc = d;
      _mcStatus = adjusted || '저장됨';
    } catch (e) {
      if (seq !== _mcSaveSeq) return;
      _mc.config = JSON.parse(_mcConfirmed);
      _mcStatus = '저장 실패: ' + e.message;
    }
    renderModelConfig();
    setTimeout(() => {
      if (_mcStatus === '저장됨') { _mcStatus = ''; ModelSelector.setStatus(document.getElementById('model-selector'), ''); }
    }, 1400);
  });
  _mcSaveChain = job.catch(() => {});
  return job;
}
