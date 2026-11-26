/* Logic thuan cua extension cuboid-qc (khong dung DOM / chrome.*), de kiem thu bang Node.
 * Dung duoc ca trong trinh duyet (globalThis.QcLib) lan Node (module.exports). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.QcLib = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const SEV_ORDER = { ERROR: 0, WARNING: 1, INFO: 2 };

  /** /tasks/38/jobs/38?frame=15 -> {taskId, jobId, frame, origin}; trang khac -> null */
  function parseJobUrl(href) {
    let u;
    try { u = new URL(href); } catch (e) { return null; }
    const m = u.pathname.match(/^\/tasks\/(\d+)\/jobs\/(\d+)\/?$/);
    if (!m) return null;
    const f = parseInt(u.searchParams.get('frame') || '0', 10);
    return { taskId: Number(m[1]), jobId: Number(m[2]), frame: Number.isNaN(f) ? 0 : f, origin: u.origin };
  }

  function csrfFromCookie(cookie) {
    const m = (cookie || '').split(';').map((s) => s.trim()).find((s) => s.startsWith('csrftoken='));
    return m ? decodeURIComponent(m.slice('csrftoken='.length)) : '';
  }

  /** Lien ket toi dung frame va chon dung doi tuong trong CVAT (serverID + type). */
  function objectUrl(origin, taskId, jobId, item) {
    const isTrack = item.kind === 'track';
    const id = isTrack ? item.track_id : item.shape_id;
    let url = `${origin}/tasks/${taskId}/jobs/${jobId}?frame=${item.frame}`;
    if (id !== null && id !== undefined) url += `&serverID=${id}&type=${isTrack ? 'track' : 'shape'}`;
    return url;
  }

  function isEmptyBody(b) {
    return !b || !((b.shapes && b.shapes.length) || (b.tracks && b.tracks.length) || (b.tags && b.tags.length));
  }

  /** Cac buoc PATCH can lam, theo thu tu an toan: xoa goi y cu -> cap nhat co -> tao goi y moi. */
  function planSteps(plan) {
    return ['delete', 'update', 'create'].filter((a) => !isEmptyBody(plan[a])).map((a) => ({ action: a, body: plan[a] }));
  }

  /** Cac chi so frame co cuboid (khong tinh 'outside'). */
  function neededFrames(ann) {
    const used = new Set();
    for (const s of ann.shapes || []) if (s.type === 'cuboid' && !s.outside) used.add(s.frame);
    for (const t of ann.tracks || []) for (const s of t.shapes || []) if (s.type === 'cuboid' && !s.outside) used.add(s.frame);
    return [...used].sort((a, b) => a - b);
  }

  function missingFrames(have, needed) {
    return needed.filter((i) => !Object.prototype.hasOwnProperty.call(have || {}, String(i)));
  }

  /** Khoa cache phia server: doi khi du lieu job doi (chunks_updated_date / so frame). */
  function jobKey(origin, jobId, meta) {
    return `${origin}|job${jobId}|${meta.chunks_updated_date || ''}|${meta.size || ''}`;
  }

  /** Ten frame theo chi so tuyet doi (CVAT danh so frame cua job tu start_frame). */
  function frameNames(meta) {
    const start = meta.start_frame || 0;
    return new Array(start).fill('').concat((meta.frames || []).map((f) => f.name));
  }

  function bytesToBase64(u8) {
    let s = '';
    const CH = 0x8000;
    for (let i = 0; i < u8.length; i += CH) s += String.fromCharCode.apply(null, u8.subarray(i, i + CH));
    return (typeof btoa === 'function' ? btoa : (x) => Buffer.from(x, 'binary').toString('base64'))(s);
  }

  function base64ToBytes(b64) {
    const bin = (typeof atob === 'function' ? atob : (x) => Buffer.from(x, 'base64').toString('binary'))(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  /** Chay worker tren tung phan tu, toi da `limit` cung luc; loi dau tien se dung het. */
  async function pool(items, limit, worker) {
    let next = 0;
    let failed = null;
    const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
      while (failed === null) {
        const i = next++;
        if (i >= items.length) return;
        try { await worker(items[i], i); } catch (e) { failed = e; return; }
      }
    });
    await Promise.all(runners);
    if (failed) throw failed;
  }

  /**
   * Luong chinh: doc nhan + label + ten frame tu CVAT, nap point cloud con thieu len server, chay QC.
   * deps.cvat   : {getJson(path), getBytes(path)}
   * deps.server : {call(method, path, {json?, bytes?}) -> Promise<{status, json}>}
   * opts        : {jobId, origin, apply, policy, onProgress(msg)}
   */
  async function runQc(deps, opts) {
    const { cvat, server } = deps;
    const say = opts.onProgress || (() => {});
    const jobId = opts.jobId;
    say('Doc nhan va thong tin job tu CVAT...');
    const [meta, ann, labelsResp] = await Promise.all([
      cvat.getJson(`/api/jobs/${jobId}/data/meta`),
      cvat.getJson(`/api/jobs/${jobId}/annotations`),
      cvat.getJson(`/api/labels?job_id=${jobId}&page_size=100`),
    ]);
    const labels = labelsResp.results || labelsResp;
    const names = frameNames(meta);
    const key = jobKey(opts.origin || '', jobId, meta);
    const needed = neededFrames(ann);

    const st = await server.call('GET', `/frames?job=${encodeURIComponent(key)}`, {});
    if (st.status !== 200) throw new Error(`Server QC: ${st.json && st.json.error ? st.json.error : 'HTTP ' + st.status}`);
    const todo = missingFrames(st.json.have, needed);
    let done = 0;
    await pool(todo, 4, async (idx) => {
      const bytes = await cvat.getBytes(`/api/jobs/${jobId}/data?type=frame&quality=original&number=${idx}`);
      const r = await server.call('PUT', `/frames/${idx}?job=${encodeURIComponent(key)}`, { bytes });
      if (r.status !== 200) throw new Error(`Nap frame ${idx} that bai: ${r.json && r.json.error ? r.json.error : r.status}`);
      done++;
      say(`Nap point cloud ${done}/${todo.length}...`);
    });

    const body = { job: key, annotations: ann, labels, frame_names: names, apply: !!opts.apply,
                   apply_policy: opts.policy || 'conservative' };
    say('Server dang chay QC...');
    let res = await server.call('POST', '/qc', { json: body });
    if (res.status === 200 && res.json.missing_frames && res.json.missing_frames.length) {
      throw new Error(`Server van thieu point cloud cua frame: ${res.json.missing_frames.join(', ')}`);
    }
    if (res.status !== 200) throw new Error(`Server QC: ${res.json && res.json.error ? res.json.error : 'HTTP ' + res.status}`);
    return { result: res.json, meta, annotations: ann, labels, uploaded: todo.length };
  }

  /** Thuc hien ke hoach ghi nguoc bang PATCH. Dung o buoc loi dau tien va bao ro buoc nao. */
  async function applyPlan(cvat, jobId, plan, onProgress) {
    const steps = planSteps(plan);
    const done = [];
    for (const s of steps) {
      if (onProgress) onProgress(`Ghi vao CVAT: ${s.action}...`);
      try {
        await cvat.patchJson(`/api/jobs/${jobId}/annotations?action=${s.action}`, s.body);
      } catch (e) {
        const err = new Error(`Ghi vao CVAT that bai o buoc "${s.action}" (da xong: ${done.join(', ') || 'khong'}): ${e.message}`);
        err.done = done;
        throw err;
      }
      done.push(s.action);
    }
    return done;
  }

  function filterItems(items, f) {
    return items.filter((it) => (!f.severity || it.severity === f.severity) && (!f.issue || it.issues.includes(f.issue)));
  }

  return { SEV_ORDER, parseJobUrl, csrfFromCookie, objectUrl, isEmptyBody, planSteps, neededFrames, missingFrames,
           jobKey, frameNames, bytesToBase64, base64ToBytes, pool, runQc, applyPlan, filterItems };
});
