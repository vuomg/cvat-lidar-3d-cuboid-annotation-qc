/* Giao dien cuboid-qc trong trang CVAT (Shadow DOM, khong dung innerHTML cho du lieu dong).
 * Logic thuan nam trong lib.js (co test bang Node). */
(function () {
  'use strict';
  const L = self.QcLib;
  if (!L || window.__cuboidQcLoaded) return;
  window.__cuboidQcLoaded = true;

  const SEV_COLOR = { ERROR: '#ef5350', WARNING: '#ffb74d', INFO: '#8b93a1' };
  const state = { job: null, open: sessionStorage.getItem('cuboidQcOpen') === '1', busy: false, last: null,
                  lastApply: false, filter: { severity: '', issue: '' }, msg: '', err: '', policy: 'conservative' };
  let host = null;
  let els = {};

  // ---------------------------------------------------------------- ket noi
  const STALE = 'Extension vừa được nạp lại hoặc cập nhật. Hãy tải lại trang (F5) rồi thử lại.';
  function friendly(e) {
    return /context invalidated|receiving end does not exist/i.test(e && e.message) ? new Error(STALE) : e;
  }

  function sendBg(msg) {
    return new Promise((resolve, reject) => {
      try {
        chrome.runtime.sendMessage(msg, (r) => {
          const e = chrome.runtime.lastError;
          if (e) reject(friendly(new Error(e.message))); else resolve(r);
        });
      } catch (e) { reject(friendly(e)); }
    });
  }

  /** Goi server QC: qua service worker; neu khong co chrome.runtime (che do thu nghiem) thi goi truc tiep. */
  const server = {
    async call(method, path, o) {
      const opts = o || {};
      if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.sendMessage) {
        const r = await sendBg({ type: 'qc-call', method, path, json: opts.json || null,
                                 bytesB64: opts.bytes ? L.bytesToBase64(opts.bytes) : null });
        if (!r) throw new Error('Extension khong phan hoi (tai lai trang?)');
        if (r.networkError) throw new Error(r.networkError);
        return { status: r.status, json: r.json };
      }
      const dev = window.__QC_DEV;
      if (!dev) throw new Error('Khong co chrome.runtime va khong co window.__QC_DEV');
      const headers = { 'X-QC-Token': dev.token };
      let body;
      if (opts.bytes) body = opts.bytes;
      else if (opts.json) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json); }
      const r = await fetch(dev.url + path, { method, headers, body });
      let json = null;
      try { json = await r.json(); } catch (e) { /* khong phai JSON */ }
      return { status: r.status, json };
    },
  };

  function makeCvat(origin) {
    const accept = { Accept: 'application/vnd.cvat+json' };
    const fail = (r, what) => new Error(`${what}: HTTP ${r.status}`);
    return {
      async getJson(path) {
        const r = await fetch(origin + path, { credentials: 'same-origin', headers: accept });
        if (!r.ok) throw fail(r, 'GET ' + path);
        return r.json();
      },
      async getBytes(path) {
        const r = await fetch(origin + path, { credentials: 'same-origin' });
        if (!r.ok) throw fail(r, 'GET ' + path);
        return new Uint8Array(await r.arrayBuffer());
      },
      async patchJson(path, body) {
        const r = await fetch(origin + path, {
          method: 'PATCH', credentials: 'same-origin',
          headers: { ...accept, 'Content-Type': 'application/json', 'X-CSRFToken': L.csrfFromCookie(document.cookie) },
          body: JSON.stringify(body),
        });
        if (!r.ok) {
          let detail = '';
          try { detail = (await r.text()).slice(0, 200); } catch (e) { /* bo qua */ }
          throw new Error(`PATCH ${path}: HTTP ${r.status} ${detail}`);
        }
      },
    };
  }

  // ---------------------------------------------------------------- DOM
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (v !== false && v !== null && v !== undefined) el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return el;
  }

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: system-ui, "Segoe UI", sans-serif; }
    .fab { position: fixed; left: 64px; bottom: 16px; width: 40px; height: 40px; border-radius: 50%; border: 0;
           background: #2e7d32; color: #fff; font-weight: 700; font-size: 13px; cursor: pointer; z-index: 2147483000;
           box-shadow: 0 2px 8px rgba(0,0,0,.4); }
    .fab .n { position: absolute; top: -4px; right: -4px; background: #ef5350; border-radius: 9px; font-size: 10px; padding: 1px 5px; }
    .panel { position: fixed; left: 16px; bottom: 64px; width: 400px; max-height: 72vh; display: flex; flex-direction: column;
             background: #1c1f26; color: #e6e8ec; border: 1px solid #333a47; border-radius: 8px; z-index: 2147483000;
             box-shadow: 0 8px 24px rgba(0,0,0,.5); font-size: 13px; }
    .hd { display: flex; align-items: center; padding: 8px 10px; border-bottom: 1px solid #2c313b; font-weight: 600; }
    .hd .x { margin-left: auto; background: none; border: 0; color: #8b93a1; font-size: 16px; cursor: pointer; }
    .row { padding: 8px 10px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
    button.b { background: #14161a; color: #e6e8ec; border: 1px solid #3a4150; border-radius: 5px; padding: 5px 9px;
               cursor: pointer; font-size: 12.5px; }
    button.b:hover:not([disabled]) { border-color: #4fc3f7; }
    button.b[disabled] { opacity: .45; cursor: default; }
    button.b.primary { border-color: #2e7d32; }
    button.b.warn { border-color: #b8860b; }
    select { background: #14161a; color: #e6e8ec; border: 1px solid #3a4150; border-radius: 4px; padding: 3px 5px; font-size: 12px; }
    .msg { padding: 0 10px 6px; color: #8b93a1; font-size: 12px; }
    .err { color: #ef5350; white-space: pre-wrap; }
    .warnbox { margin: 0 10px 6px; padding: 5px 8px; background: #3a2f12; color: #ffcc66; border-radius: 4px; font-size: 12px; }
    .chips { padding: 0 10px 6px; display: flex; gap: 5px; flex-wrap: wrap; }
    .chip { background: #262b36; border-radius: 10px; padding: 1px 8px; font-size: 11.5px; cursor: pointer; border: 1px solid transparent; }
    .chip.on { border-color: #4fc3f7; }
    .list { overflow: auto; flex: 1; border-top: 1px solid #2c313b; min-height: 60px; }
    .it { display: flex; gap: 8px; padding: 7px 10px; border-bottom: 1px solid #252a34; cursor: pointer; }
    .it:hover { background: #232733; } .it.act { background: #2a3040; }
    .grow { flex: 1; min-width: 0; }
    .fh { position: sticky; top: 0; z-index: 1; display: flex; align-items: center; gap: 8px; padding: 4px 10px; cursor: pointer;
          background: #20242d; border-bottom: 1px solid #2c313b; font-size: 12px; font-weight: 600; color: #cfd6e2; }
    .fh:hover { background: #262b36; } .fh .c { margin-left: auto; font-weight: 400; color: #8b93a1; }
    .cid { align-self: flex-start; flex: none; min-width: 34px; text-align: center; border-radius: 4px; padding: 1px 5px;
           font-size: 12px; font-weight: 700; background: #2f3b52; color: #cfe4ff; border: 1px solid #44567a; }
    .cid.na { background: #2a2d35; color: #8b93a1; border-color: #3a4150; font-weight: 400; }
    .dot { width: 9px; height: 9px; border-radius: 50%; margin-top: 4px; flex: none; }
    .t { font-weight: 600; } .m { color: #8b93a1; font-size: 12px; }
    .note { color: #aab1be; font-size: 11.5px; word-break: break-word; }
    .fix { color: #66bb6a; font-size: 11.5px; } .auto { background: #1f3d27; border-radius: 6px; padding: 0 5px; margin-left: 4px; }
    .empty { padding: 14px 10px; color: #8b93a1; }
  `;

  /** replaceChildren nhung bo qua null / false (tranh chu "null" lot vao giao dien). */
  function put(el, ...nodes) {
    el.replaceChildren(...nodes.flat().filter((n) => n !== null && n !== undefined && n !== false));
  }

  // ---------------------------------------------------------------- luu ket qua qua cac lan tai lai trang
  const storeKey = () => `cuboidQc:last:${state.job.origin}:${state.job.jobId}`;

  function saveLast() {
    try {
      const r = state.last.result;     // khong luu `plan` (co the rat lon); ghi can chay lai QC de co ke hoach
      sessionStorage.setItem(storeKey(), JSON.stringify({ ts: Date.now(), apply: state.lastApply,
        result: { summary: r.summary, items: r.items, warnings: r.warnings, can_write: r.can_write, stats: r.stats } }));
    } catch (e) { /* day bo nho: bo qua, chi mat tinh nang khoi phuc */ }
  }

  function restoreLast() {
    try {
      const raw = sessionStorage.getItem(storeKey());
      if (!raw) return;
      const o = JSON.parse(raw);
      state.last = { result: { ...o.result, plan: null }, restoredAt: o.ts };
      state.lastApply = !!o.apply;
    } catch (e) { /* du lieu hong: bo qua */ }
  }

  function build() {
    host = h('div', { id: 'cuboid-qc-root' });
    for (const ev of ['keydown', 'keyup', 'keypress']) host.addEventListener(ev, (e) => e.stopPropagation());   // khong kich hoat phim tat CVAT
    const root = host.attachShadow({ mode: 'open' });
    els.fab = h('button', { class: 'fab', title: 'Cuboid QC', onclick: toggle }, 'QC');
    els.panel = h('div', { class: 'panel' });
    root.append(h('style', {}, CSS), els.fab, els.panel);
    document.documentElement.append(host);
  }

  function issueCounts() {
    const r = state.last && state.last.result;
    return r ? r.summary.by_issue : {};
  }

  function render() {
    if (!host) return;
    host.style.display = state.job ? '' : 'none';
    const r = state.last && state.last.result;
    // nut tron: so loi
    put(els.fab, 'QC', r && r.summary.flagged ? h('span', { class: 'n' }, r.summary.flagged) : null);
    els.panel.style.display = state.open ? '' : 'none';
    if (!state.open) return;

    // ket qua khoi phuc sau khi tai lai trang khong con ke hoach (plan): khi bam Ghi se tu chay lai QC de tinh
    const canWrite = !!(r && r.can_write && (!r.plan || L.planSteps(r.plan).length)) && !state.busy;
    const items = r ? L.filterItems(r.items, state.filter) : [];
    const issues = Object.keys(issueCounts());

    const header = h('div', { class: 'hd' }, 'Cuboid QC', h('span', { class: 'm', style: 'margin-left:8px;font-weight:400' },
      state.job ? `job ${state.job.jobId}` : ''), h('button', { class: 'x', onclick: toggle, title: 'Đóng' }, '×'));

    const buttons = h('div', { class: 'row' },
      h('button', { class: 'b primary', disabled: state.busy, onclick: () => run(false) }, 'Chạy QC'),
      h('button', { class: 'b warn', disabled: state.busy, onclick: () => run(true),
                    title: state.policy === 'all' ? 'Chính sách "all": áp dụng mọi gợi ý (có thể làm hỏng nhãn đúng)' :
                      'Chỉ tự sửa loại an toàn (lật hướng khi ERROR, sửa kích thước theo track)' }, 'Tự sửa (xem trước)'),
      h('button', { class: 'b', disabled: !canWrite, onclick: write },
        state.lastApply ? 'Ghi thay đổi tự sửa vào job' : 'Ghi cờ & gợi ý vào job'));

    const status = [];
    if (state.busy || state.msg) status.push(h('div', { class: 'msg' }, state.msg));
    if (state.err) status.push(h('div', { class: 'msg err' }, state.err));
    if (r) {
      status.push(h('div', { class: 'msg' }, `${r.summary.cuboids} cuboid, ${r.summary.flagged} bị cờ` +
        (state.lastApply ? ` | sẽ tự sửa ${r.stats.applied}, giữ lại ${r.stats.skipped} gợi ý cho người quyết định` : '')));
      if (state.last.restoredAt) {
        const mins = Math.max(0, Math.round((Date.now() - state.last.restoredAt) / 60000));
        status.push(h('div', { class: 'msg' }, `Kết quả lưu từ ${mins} phút trước (tải lại trang không làm mất). Bấm "Chạy QC" để cập nhật.`));
      }
      for (const w of r.warnings) status.push(h('div', { class: 'warnbox' }, w));
    }

    const chips = h('div', { class: 'chips' }, issues.map((i) => h('span', {
      class: 'chip' + (state.filter.issue === i ? ' on' : ''),
      onclick: () => { state.filter.issue = state.filter.issue === i ? '' : i; render(); },
    }, `${i} ${issueCounts()[i]}`)));

    const sevSel = h('select', { onchange: (e) => { state.filter.severity = e.target.value; render(); } },
      ['', 'ERROR', 'WARNING'].map((s) => h('option', { value: s, selected: state.filter.severity === s }, s || 'Mọi mức')));

    ensureUiIds();
    const itemRow = (it) => {
      const cid = L.uiIdOf(state.uiIds, it);
      return h('div', { class: 'it' + (state.active === it.token ? ' act' : ''), onclick: () => go(it),
                        title: 'Bấm: nhảy tới frame và chọn đối tượng này trong danh sách bên phải của CVAT' },
        h('span', { class: 'dot', style: `background:${SEV_COLOR[it.severity]}` }),
        h('span', { class: 'cid' + (cid === null ? ' na' : ''),
                    title: cid === null ? 'Chưa xác định được ID trong CVAT' :
                      `ID đối tượng hiển thị ở danh sách bên phải của CVAT (track ${it.track_id !== null && it.track_id !== undefined ? it.track_id : '-'})` },
          cid === null ? '?' : '#' + cid),
        h('div', { class: 'grow' },
          h('div', { class: 't' }, it.issues.join(', ')),
          h('div', { class: 'm' }, `${it.label} · ${it.severity}` + (it.pos ? ` · x=${it.pos[0]}, y=${it.pos[1]} (${it.dist} m)` : '')),
          h('div', { class: 'note' }, it.notes[0] || ''),
          it.fix ? h('div', { class: 'fix' }, it.fix.text, it.fix.auto ? h('span', { class: 'auto' }, 'tự sửa') : null) : null));
    };
    const groups = r ? L.groupByFrame(items, state.uiIds) : [];
    const list = h('div', { class: 'list' }, !r ? h('div', { class: 'empty' }, 'Bấm "Chạy QC" để kiểm tra job này.') :
      !items.length ? h('div', { class: 'empty' }, r.items.length ? 'Không có lỗi khớp bộ lọc.' : 'Không phát hiện lỗi nào.') :
      groups.map((g) => [
        h('div', { class: 'fh', title: 'Nhảy tới frame này', onclick: () => jumpToFrame(g.frame) },
          `Frame ${g.frame}`, h('span', { class: 'c' }, `${g.items.length} lỗi`)),
        ...g.items.map(itemRow)]));

    put(els.panel, header, buttons, ...status, r ? chips : null, r ? h('div', { class: 'row' }, sevSel) : null, list);
  }

  // ---------------------------------------------------------------- hanh dong
  function setMsg(msg, err) {
    state.msg = msg || '';
    state.err = err || '';
    render();
  }

  async function run(apply) {
    if (state.busy || !state.job) return;
    state.busy = true;
    state.lastApply = apply;
    setMsg('Bắt đầu...');
    try {
      const out = await L.runQc({ cvat: makeCvat(state.job.origin), server }, {
        jobId: state.job.jobId, origin: state.job.origin, apply, policy: state.policy, onProgress: (m) => setMsg(m) });
      state.last = out;
      state.uiIds = L.uiIdMap(out.annotations);      // ID hien trong danh sach doi tuong cua CVAT (tinh tu cung annotation)
      state.busy = false;
      saveLast();
      setMsg(out.uploaded ? `Đã nạp ${out.uploaded} frame point cloud lần đầu.` : '');
    } catch (e) {
      state.busy = false;
      setMsg('', e.message);
    }
  }

  async function write() {
    if (!state.last || state.busy) return;
    if (!state.last.result.plan) {                 // ket qua khoi phuc: chua co ke hoach ghi -> tinh lai
      await run(state.lastApply);
      if (state.err || !state.last || !state.last.result.plan) return;
    }
    const r = state.last.result;
    const lines = [
      state.lastApply ? `Sẽ GHI THAY ĐỔI TỰ SỬA vào job ${state.job.jobId}: sửa ${r.stats.applied} box.` :
        `Sẽ ghi vào job ${state.job.jobId}: ${r.summary.flagged} cờ (thuộc tính qc_issue / qc_note) và ${r.stats.suggestions} cuboid gợi ý QC_SUGGESTION.`,
      '', 'Hãy LƯU mọi thay đổi chưa lưu trong CVAT trước (Ctrl+S). Trang sẽ tải lại sau khi ghi.',
    ];
    if (state.lastApply && state.policy === 'all') lines.push('', 'CẢNH BÁO: chính sách "all" có thể làm hỏng nhãn đúng.');
    if (!window.confirm(lines.join('\n'))) return;
    state.busy = true;
    try {
      await L.applyPlan(makeCvat(state.job.origin), state.job.jobId, r.plan, (m) => setMsg(m));
      state.busy = false;
      setMsg('Đã ghi vào CVAT. Đang tải lại trang...');
      setTimeout(() => location.reload(), 700);
    } catch (e) {
      state.busy = false;
      setMsg('', e.message);
    }
  }

  /** Dat o 'frame' cua CVAT (antd InputNumber) ve frame n va nhan Enter. Tra ve false neu khong tim thay o do. */
  function jumpToFrame(n) {
    const input = document.querySelector('.cvat-player-frame-selector input');
    if (!input) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    input.focus();
    setter.call(input, String(n));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    const ev = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true };
    input.dispatchEvent(new KeyboardEvent('keydown', ev));
    input.dispatchEvent(new KeyboardEvent('keyup', ev));
    input.blur();
    return true;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const currentFrame = () => {
    const input = document.querySelector('.cvat-player-frame-selector input');
    return input ? Number(input.value) : null;
  };

  /**
   * Chon doi tuong co ID `cid` trong danh sach ben phai cua CVAT: cuon danh sach (la danh sach ao, chi dung phan dang hien)
   * den khi muc xuat hien, roi mo phong re chuot len muc do (CVAT kich hoat doi tuong khi re chuot).
   * Danh sach xep tang dan theo ID nen tim nhi phan theo vi tri cuon; neu nguoi dung doi cach xep thi quet tuan tu.
   */
  async function activateInSidebar(cid) {
    const box = document.querySelector('.cvat-virtual-list-viewport');
    if (!box) return false;
    const idsNow = () => [...box.querySelectorAll('.cvat-objects-sidebar-state-item')].map((e) => Number(e.id.split('-').pop()));
    const find = () => document.getElementById('cvat-objects-sidebar-state-item-' + cid);
    let el = find();
    let lo = 0;
    let hi = Math.max(0, box.scrollHeight - box.clientHeight);
    for (let i = 0; i < 14 && !el; i++) {                    // tim nhi phan
      box.scrollTop = Math.floor((lo + hi) / 2);
      await sleep(130);
      el = find();
      if (el) break;
      const ids = idsNow();
      if (!ids.length) continue;
      if (Math.min(...ids) > cid) hi = Math.floor((lo + hi) / 2); else lo = Math.floor((lo + hi) / 2);
    }
    for (let y = 0; !el && y <= box.scrollHeight; y += Math.max(60, box.clientHeight * 0.8)) {   // du phong: quet tuan tu
      box.scrollTop = y;
      await sleep(130);
      el = find();
    }
    if (!el) return false;
    el.scrollIntoView({ block: 'center' });
    await sleep(150);
    const r = el.getBoundingClientRect();
    const opts = { bubbles: true, cancelable: true, view: window, clientX: r.left + r.width / 2, clientY: r.top + 20 };
    for (const t of ['pointerover', 'mouseover', 'mouseenter', 'pointermove', 'mousemove']) el.dispatchEvent(new MouseEvent(t, opts));
    return true;
  }

  /** Bam vao loi: nhay toi frame ngay trong trang (giu ket qua QC) roi chon dung doi tuong trong danh sach cua CVAT. */
  async function go(item) {
    state.active = item.token;
    render();
    if (currentFrame() !== item.frame) {
      if (!jumpToFrame(item.frame)) return openObject(item);
      for (let i = 0; i < 12 && currentFrame() !== item.frame; i++) await sleep(100);
      if (currentFrame() !== item.frame) return openObject(item);
      await sleep(700);                                      // doi CVAT dung xong danh sach doi tuong cua frame moi
    }
    const cid = L.uiIdOf(state.uiIds, item);
    if (cid !== null) await activateInSidebar(cid);
  }

  /** Du phong khi khong dat duoc o frame: mo bang lien ket (tai lai trang; ket qua QC duoc khoi phuc tu sessionStorage). */
  function openObject(item) {
    saveLast();
    location.href = L.objectUrl(state.job.origin, state.job.taskId, state.job.jobId, item);
  }

  /** ID CVAT cua tung doi tuong: tinh tu annotation hien tai tren server (cung trang thai giao dien da tai). */
  function ensureUiIds() {
    if (state.uiIds || state.uiIdsLoading || !state.job || !state.last) return;
    state.uiIdsLoading = true;
    makeCvat(state.job.origin).getJson(`/api/jobs/${state.job.jobId}/annotations`)
      .then((ann) => { state.uiIds = L.uiIdMap(ann); })
      .catch(() => { /* khong co ID thi hien dau ? */ })
      .finally(() => { state.uiIdsLoading = false; render(); });
  }

  function toggle() {
    state.open = !state.open;
    sessionStorage.setItem('cuboidQcOpen', state.open ? '1' : '0');
    render();
  }

  // ---------------------------------------------------------------- vong doi (CVAT la SPA: URL doi khong tai lai trang)
  function sync() {
    const job = L.parseJobUrl(location.href);
    const changed = (job && job.jobId) !== (state.job && state.job.jobId);
    state.job = job;
    if (changed) {
      state.last = null; state.msg = ''; state.err = ''; state.active = null; state.uiIds = null;
      if (job) restoreLast();
    }
    if (!host) build();
    if (changed || !els.panel.childElementCount) render();
    else if (host) host.style.display = job ? '' : 'none';
  }

  function init() {
    try {
      if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.sendMessage) {
        sendBg({ type: 'qc-settings' }).then((s) => { if (s && s.policy) { state.policy = s.policy; render(); } }).catch(() => {});
      }
    } catch (e) { /* che do thu nghiem */ }
    sync();
    setInterval(sync, 1000);
  }

  window.__cuboidQc = { state, run, toggle, render };      // de kiem thu / go loi
  init();
})();
