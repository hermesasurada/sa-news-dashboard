/* 용어 툴팁 — sa·td 공용(글자 단위로 같은 파일을 두 저장소에 둔다, 2026-11-18 사용자 지시).
   카드 요약 속 용어에 점선 밑줄을 달고, 누르면 뜻풀이 창을 띄운다(인명 소개와 같은 방식).
   yt·wm처럼 본문에 각주를 넣지 않는다. 뜻풀이는 공용 용어집(hermes-llm-log/term_glossary —
   yt·wm 요약 각주를 모은 것)에서 서비스 서버의 /api/terms가 찾아 준다.
   카드마다 같은 용어는 첫 등장 한 번만. ✕는 그 뜻을 sa·td 공통으로 뺀다(공용 DB).
   카드는 목록 컨테이너를 지켜보다가(MutationObserver) 새로 붙은 것만 묶어서 묻는다 — 무한 스크롤·
   페이지 이동·빈자리 보충 경로를 따로 고칠 필요가 없다. */
(function (w) {
  "use strict";
  const esc = (x) => String(x ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const reEsc = (x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const HANGUL = /[가-힣]/;
  const WORD = /[A-Za-z0-9]/;
  const JOSA = "은는이가을를의에와과도로으만까부처보랑나엔서께며라란인적";   // 서버(term_glossary)와 같은 규칙
  const SRC = {yt: "yt", wm: "wm"};

  function okBoundary(text, start, end, form) {
    const prev = text[start - 1] || " ", next = text[end] || " ";
    if (HANGUL.test(form[0])) return !HANGUL.test(prev) && (!HANGUL.test(next) || JOSA.includes(next));
    return !WORD.test(prev) && !WORD.test(next);
  }

  function mount(opt) {
    const o = Object.assign({
      endpoint: "/api/terms", excludeEndpoint: "/api/terms/excluded",
      card: ".card[data-id]", text: ".summary",
      skip: "a, button, .person-name, .term-tip, .ticker-badge, .ticker-chip",
      headers: (h) => h,
    }, opt || {});
    const root = document.querySelector(o.container);
    if (!root) return null;
    const asked = new WeakSet();
    let tip = null, timer = 0;
    const pending = new Set();

    function place(anchor) {
      const r = anchor.getBoundingClientRect(), m = 12;
      tip.style.left = "0px"; tip.style.top = "0px";
      const wd = tip.offsetWidth, h = tip.offsetHeight;
      const left = Math.min(Math.max(m, r.left + r.width / 2 - wd / 2), window.innerWidth - wd - m);
      const below = r.bottom + 8 + h <= window.innerHeight - m;
      tip.style.left = left + "px";
      tip.style.top = (below ? r.bottom + 8 : Math.max(m, r.top - 8 - h)) + "px";
      tip.classList.toggle("above", !below);
      tip.style.setProperty("--arrow-x", Math.min(Math.max(14, r.left + r.width / 2 - left), wd - 14) + "px");
    }
    async function setExcluded(key, excluded) {
      try {
        const r = await fetch(o.excludeEndpoint, {method: "POST", headers: o.headers({"Content-Type": "application/json"}),
                                                  body: JSON.stringify({key, excluded})});
        return !!(await r.json()).ok;
      } catch (e) { return false; }
    }
    const unwrapKey = (key) => root.querySelectorAll(".term-tip").forEach((el) => {
      if (el.dataset.key !== key) return;
      const parent = el.parentNode; el.replaceWith(document.createTextNode(el.textContent)); parent.normalize();
    });
    function hide() { if (tip) tip.classList.remove("show"); }
    function show(item, anchor) {
      if (!tip) {
        tip = document.createElement("div");
        tip.id = "term-tip-pop";
        tip.setAttribute("role", "dialog");
        document.body.appendChild(tip);
        document.addEventListener("click", (e) => {
          if (!e.target.closest("#term-tip-pop") && !e.target.closest(".term-tip")) hide();
        }, true);
        document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
        document.addEventListener("scroll", (e) => { if (!tip.contains(e.target)) hide(); }, true);
        window.addEventListener("resize", hide);
      }
      const sub = [item.full_name, item.korean && item.korean !== item.term ? item.korean : ""].filter(Boolean);
      const src = (item.sources || []).map((s) => SRC[s] || s).join("·");
      tip.innerHTML = `<div class="tt-name">${esc(item.term)}${sub.length ? ` <span class="tt-sub">${esc(sub.join(" · "))}</span>` : ""}</div>`
        + `<div class="tt-def">${esc(item.definition)}</div>`
        + `<div class="tt-foot">${src ? `<span class="tt-src">${esc(src)} 각주</span>` : ""}`
        + `<button type="button" class="tt-ex" title="이 뜻을 용어 툴팁에서 뺍니다(sa·td 공통)">✕ 용어 툴팁 제외</button></div>`;
      tip.querySelector(".tt-ex").onclick = async (e) => {
        e.stopPropagation();
        if (!(await setExcluded(item.key, true))) return;
        unwrapKey(item.key);
        tip.querySelector(".tt-foot").innerHTML = `<span class="tt-done">제외했습니다</span><button type="button" class="tt-undo">되돌리기</button>`;
        tip.querySelector(".tt-undo").onclick = async (ev) => {
          ev.stopPropagation();
          if (!(await setExcluded(item.key, false))) return;
          hide();
          refreshAll();
        };
      };
      tip.classList.add("show");
      place(anchor);
    }
    function decorate(card, items) {
      const list = (items || []).filter((t) => t.definition && (t.forms || []).length);
      if (!list.length) return;
      const done = new Set([...card.querySelectorAll(".term-tip")].map((e) => e.dataset.key));
      const forms = [];
      list.forEach((t, i) => t.forms.forEach((f) => forms.push({f, i})));
      forms.sort((a, b) => b.f.length - a.f.length);
      const byForm = new Map(forms.map((x) => [x.f, x.i]));
      const re = new RegExp(forms.map((x) => reEsc(x.f)).join("|"), "g");
      card.querySelectorAll(o.text).forEach((textRoot) => {
        const walker = document.createTreeWalker(textRoot, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach((node) => {
          if (!node.parentElement || node.parentElement.closest(o.skip)) return;
          const text = node.nodeValue;
          let m, last = 0, frag = null;
          re.lastIndex = 0;
          while ((m = re.exec(text))) {
            const i = byForm.get(m[0]);
            if (i === undefined || !okBoundary(text, m.index, m.index + m[0].length, m[0])) continue;
            const item = list[i];
            if (done.has(item.key)) continue;                       // 카드마다 첫 등장 한 번만
            done.add(item.key);
            frag = frag || document.createDocumentFragment();
            frag.appendChild(document.createTextNode(text.slice(last, m.index)));
            const span = document.createElement("span");
            span.className = "term-tip";
            span.dataset.key = item.key;
            span.textContent = m[0];
            span.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); show(item, span); });
            frag.appendChild(span);
            last = m.index + m[0].length;
          }
          if (frag) { frag.appendChild(document.createTextNode(text.slice(last))); node.parentNode.replaceChild(frag, node); }
        });
      });
    }
    async function load(cards) {
      for (let i = 0; i < cards.length; i += 100) {
        const chunk = cards.slice(i, i + 100);
        try {
          const r = await fetch(o.endpoint + "?ids=" + chunk.map((c) => c.dataset.id).join(","));
          const map = await r.json();
          chunk.forEach((c) => { if (c.isConnected) decorate(c, map[c.dataset.id]); });
        } catch (e) { /* 툴팁은 부가 기능 — 실패해도 카드는 그대로 */ }
      }
    }
    function flush() {
      const cards = [...pending].filter((c) => c.isConnected);
      pending.clear();
      if (cards.length) load(cards);
    }
    function scan() {
      root.querySelectorAll(o.card).forEach((c) => {
        if (asked.has(c) || !c.dataset.id) return;
        asked.add(c);
        pending.add(c);
      });
      if (pending.size) { clearTimeout(timer); timer = setTimeout(flush, 80); }
    }
    function refreshAll() { load([...root.querySelectorAll(o.card)].filter((c) => c.dataset.id)); }
    new MutationObserver(scan).observe(root, {childList: true, subtree: true});
    scan();
    return {refresh: refreshAll};
  }
  w.HermesTermTips = {mount};
})(window);
