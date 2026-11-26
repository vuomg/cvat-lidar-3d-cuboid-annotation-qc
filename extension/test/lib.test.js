// Chay: node --test extension/test
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../lib.js');

test('parseJobUrl: trang job hop le', () => {
  assert.deepEqual(L.parseJobUrl('http://localhost:8080/tasks/38/jobs/38?frame=15'),
    { taskId: 38, jobId: 38, frame: 15, origin: 'http://localhost:8080' });
  assert.equal(L.parseJobUrl('https://cvat.edufun.ai/tasks/7/jobs/12/').jobId, 12);
  assert.equal(L.parseJobUrl('http://localhost:8080/tasks/38/jobs/38').frame, 0);
});

test('parseJobUrl: trang khac / URL hong -> null', () => {
  for (const u of ['http://localhost:8080/tasks', 'http://localhost:8080/tasks/38', 'http://localhost:8080/jobs/38',
    'http://127.0.0.1:8766/health', 'khong phai url', '']) assert.equal(L.parseJobUrl(u), null, u);
});

test('parseJobUrl: frame khong phai so -> 0', () => {
  assert.equal(L.parseJobUrl('http://x/tasks/1/jobs/2?frame=abc').frame, 0);
});

test('csrfFromCookie', () => {
  assert.equal(L.csrfFromCookie('a=1; csrftoken=abc%3D123; b=2'), 'abc=123');
  assert.equal(L.csrfFromCookie('sessionid=zzz'), '');
  assert.equal(L.csrfFromCookie(''), '');
  assert.equal(L.csrfFromCookie('xcsrftoken=nope'), '');
});

test('objectUrl: track va shape', () => {
  assert.equal(L.objectUrl('http://h', 3, 4, { kind: 'track', track_id: 41, frame: 15 }),
    'http://h/tasks/3/jobs/4?frame=15&serverID=41&type=track');
  assert.equal(L.objectUrl('http://h', 3, 4, { kind: 'shape', shape_id: 9, frame: 2 }),
    'http://h/tasks/3/jobs/4?frame=2&serverID=9&type=shape');
  assert.equal(L.objectUrl('http://h', 3, 4, { kind: 'shape', shape_id: null, frame: 2 }), 'http://h/tasks/3/jobs/4?frame=2');
});

test('planSteps: dung thu tu, bo qua buoc rong', () => {
  const full = { delete: { shapes: [{ id: 1 }], tracks: [], tags: [] }, update: { shapes: [], tracks: [{ id: 2 }], tags: [] },
    create: { shapes: [{}], tracks: [], tags: [] } };
  assert.deepEqual(L.planSteps(full).map((s) => s.action), ['delete', 'update', 'create']);
  const some = { delete: { shapes: [], tracks: [], tags: [] }, update: { shapes: [], tracks: [{ id: 2 }], tags: [] },
    create: { shapes: [], tracks: [], tags: [] } };
  assert.deepEqual(L.planSteps(some).map((s) => s.action), ['update']);
  assert.deepEqual(L.planSteps({}), []);
});

test('neededFrames: bo outside va lop khong phai cuboid', () => {
  const ann = { shapes: [{ type: 'cuboid', frame: 5 }, { type: 'rectangle', frame: 9 }, { type: 'cuboid', frame: 7, outside: true }],
    tracks: [{ shapes: [{ type: 'cuboid', frame: 1 }, { type: 'cuboid', frame: 2, outside: true }, { type: 'cuboid', frame: 5 }] }] };
  assert.deepEqual(L.neededFrames(ann), [1, 5]);
});

test('missingFrames', () => {
  assert.deepEqual(L.missingFrames({ 0: 10, 2: 10 }, [0, 1, 2, 3]), [1, 3]);
  assert.deepEqual(L.missingFrames(null, [4]), [4]);
});

test('frameNames: job bat dau tu frame > 0 duoc dem de chi so la tuyet doi', () => {
  assert.deepEqual(L.frameNames({ start_frame: 2, frames: [{ name: 'a' }, { name: 'b' }] }), ['', '', 'a', 'b']);
  assert.deepEqual(L.frameNames({ frames: [{ name: 'a' }] }), ['a']);
});

test('base64: khu hoi voi du lieu nhi phan lon (khong tran stack)', () => {
  const u8 = new Uint8Array(600000);
  for (let i = 0; i < u8.length; i++) u8[i] = (i * 31 + 7) & 255;
  const back = L.base64ToBytes(L.bytesToBase64(u8));
  assert.equal(back.length, u8.length);
  assert.ok(back.every((v, i) => v === u8[i]));
});

test('pool: gioi han dong thoi va xu ly het', async () => {
  let running = 0, peak = 0;
  const seen = [];
  await L.pool([...Array(20).keys()], 4, async (x) => {
    running++; peak = Math.max(peak, running);
    await new Promise((r) => setTimeout(r, 2));
    seen.push(x); running--;
  });
  assert.equal(seen.length, 20);
  assert.ok(peak <= 4 && peak >= 2, `peak=${peak}`);
});

test('pool: loi dau tien duoc nem ra va dung viec moi', async () => {
  const started = [];
  await assert.rejects(L.pool([...Array(50).keys()], 2, async (x) => {
    started.push(x);
    if (x === 3) throw new Error('hong');
    await new Promise((r) => setTimeout(r, 1));
  }), /hong/);
  assert.ok(started.length < 50);
});

// ---------- runQc voi CVAT / server gia ----------
function fakes(opts = {}) {
  const calls = [];
  const have = opts.have || {};
  const cvat = {
    async getJson(path) {
      calls.push(['cvat.json', path]);
      if (path.includes('/data/meta')) return { frames: [{ name: '0.pcd' }, { name: '1.pcd' }, { name: '2.pcd' }], size: 3, chunks_updated_date: 'D', start_frame: 0 };
      if (path.includes('/annotations')) return { shapes: [], tracks: [{ shapes: [{ type: 'cuboid', frame: 0 }, { type: 'cuboid', frame: 1 }, { type: 'cuboid', frame: 2 }] }] };
      if (path.includes('/api/labels')) return { results: [{ id: 1, name: 'Car', attributes: [] }] };
      throw new Error('bat ngo ' + path);
    },
    async getBytes(path) { calls.push(['cvat.bytes', path]); return new Uint8Array([1, 2, 3]); },
  };
  let qcCalls = 0;
  const server = {
    async call(method, path, o) {
      calls.push(['server', method, path.split('?')[0]]);
      if (method === 'GET') return { status: 200, json: { have } };
      if (method === 'PUT') { have[path.match(/\/frames\/(\d+)/)[1]] = 3; return { status: opts.putStatus || 200, json: { ok: true } }; }
      qcCalls++;
      if (opts.stillMissing) return { status: 200, json: { missing_frames: [1] } };
      return { status: 200, json: { summary: { flagged: 0 }, items: [], plan: {}, missing_frames: [], body: o.json } };
    },
  };
  return { cvat, server, calls };
}

test('runQc: chi nap frame con thieu, roi goi /qc voi du lieu dung', async () => {
  const f = fakes({ have: { 1: 3 } });
  const out = await L.runQc(f, { jobId: 38, origin: 'http://h', policy: 'all' });
  const puts = f.calls.filter((c) => c[0] === 'server' && c[1] === 'PUT').map((c) => c[2]).sort();
  assert.deepEqual(puts, ['/frames/0', '/frames/2']);
  assert.equal(out.uploaded, 2);
  const body = out.result.body;
  assert.deepEqual(body.frame_names, ['0.pcd', '1.pcd', '2.pcd']);
  assert.equal(body.apply_policy, 'all');
  assert.equal(body.apply, false);
  assert.ok(body.job.startsWith('http://h|job38|D|3'));
  assert.equal(body.labels[0].name, 'Car');
});

test('runQc: cache day du thi khong nap lai frame nao', async () => {
  const f = fakes({ have: { 0: 3, 1: 3, 2: 3 } });
  const out = await L.runQc(f, { jobId: 1, origin: 'o' });
  assert.equal(out.uploaded, 0);
  assert.equal(f.calls.filter((c) => c[0] === 'cvat.bytes').length, 0);
});

test('runQc: nap frame that bai -> loi ro rang', async () => {
  const f = fakes({ putStatus: 400 });
  await assert.rejects(L.runQc(f, { jobId: 1, origin: 'o' }), /Nap frame \d+ that bai/);
});

test('runQc: server van bao thieu frame -> loi, khong tra ket qua sai', async () => {
  const f = fakes({ have: { 0: 3, 1: 3, 2: 3 }, stillMissing: true });
  await assert.rejects(L.runQc(f, { jobId: 1, origin: 'o' }), /thieu point cloud cua frame: 1/);
});

test('runQc: bao tien do', async () => {
  const f = fakes();
  const msgs = [];
  await L.runQc(f, { jobId: 1, origin: 'o', onProgress: (m) => msgs.push(m) });
  assert.ok(msgs.some((m) => /Nap point cloud 3\/3/.test(m)));
  assert.ok(msgs.some((m) => /chay QC/.test(m)));
});

// ---------- applyPlan ----------
test('applyPlan: PATCH dung thu tu va dung action', async () => {
  const sent = [];
  const cvat = { async patchJson(path, body) { sent.push([path, body]); } };
  const plan = { delete: { shapes: [{ id: 1 }], tracks: [], tags: [] }, update: { shapes: [], tracks: [{ id: 2 }], tags: [] },
    create: { shapes: [{ type: 'cuboid' }], tracks: [], tags: [] } };
  const done = await L.applyPlan(cvat, 36, plan);
  assert.deepEqual(done, ['delete', 'update', 'create']);
  assert.deepEqual(sent.map((s) => s[0]), ['/api/jobs/36/annotations?action=delete', '/api/jobs/36/annotations?action=update',
    '/api/jobs/36/annotations?action=create']);
});

test('applyPlan: dung o buoc loi va noi ro buoc nao da xong', async () => {
  const cvat = { async patchJson(path) { if (path.includes('action=update')) throw new Error('HTTP 400'); } };
  const plan = { delete: { shapes: [{ id: 1 }] }, update: { tracks: [{ id: 2 }] }, create: { shapes: [{}] } };
  await assert.rejects(L.applyPlan(cvat, 36, plan), (e) => {
    assert.match(e.message, /buoc "update"/);
    assert.match(e.message, /da xong: delete/);
    assert.deepEqual(e.done, ['delete']);
    return true;
  });
});

test('applyPlan: ke hoach rong thi khong goi mang', async () => {
  let n = 0;
  const done = await L.applyPlan({ async patchJson() { n++; } }, 1, { delete: {}, update: { shapes: [] }, create: null });
  assert.deepEqual(done, []);
  assert.equal(n, 0);
});

test('uiIdMap: danh so theo [tags, shapes, tracks] nhu giao dien CVAT', () => {
  // du lieu that cua job demo: 10 shape (QC_SUGGESTION), 36 track; track dau co serverID 48 -> ID 11; track 60 -> ID 23
  const ann = { tags: [], shapes: Array.from({ length: 10 }, (_, i) => ({ id: 100 + i })),
    tracks: Array.from({ length: 36 }, (_, i) => ({ id: 48 + i })) };
  const m = L.uiIdMap(ann);
  assert.equal(m.shape[100], 1);
  assert.equal(m.shape[109], 10);
  assert.equal(m.track[48], 11);
  assert.equal(m.track[60], 23);
  assert.equal(m.track[83], 46);
});

test('uiIdMap: tags dem truoc shapes; thieu id thi bo qua', () => {
  const m = L.uiIdMap({ tags: [{}, {}], shapes: [{ id: 5 }, {}], tracks: [{ id: 9 }] });
  assert.equal(m.shape[5], 3);
  assert.equal(m.track[9], 5);                    // 2 tag + 2 shape (1 khong id van duoc dem) + track
  assert.deepEqual(L.uiIdMap({}), { track: {}, shape: {} });
});

test('uiIdOf', () => {
  const m = L.uiIdMap({ shapes: [{ id: 7 }], tracks: [{ id: 3 }] });
  assert.equal(L.uiIdOf(m, { kind: 'track', track_id: 3 }), 2);
  assert.equal(L.uiIdOf(m, { kind: 'shape', shape_id: 7 }), 1);
  assert.equal(L.uiIdOf(m, { kind: 'track', track_id: 999 }), null);
  assert.equal(L.uiIdOf(null, { kind: 'track', track_id: 3 }), null);
});

test('groupByFrame: frame tang dan, ERROR truoc, roi theo ID CVAT', () => {
  const m = L.uiIdMap({ tracks: [{ id: 1 }, { id: 2 }, { id: 3 }] });          // ID CVAT 1, 2, 3
  const mk = (track_id, frame, severity) => ({ kind: 'track', track_id, frame, severity, token: `t${track_id}:${frame}`, issues: [] });
  const g = L.groupByFrame([mk(3, 5, 'ERROR'), mk(1, 2, 'WARNING'), mk(2, 5, 'WARNING'), mk(1, 5, 'ERROR')], m);
  assert.deepEqual(g.map((x) => x.frame), [2, 5]);
  assert.deepEqual(g[1].items.map((i) => i.token), ['t1:5', 't3:5', 't2:5']);     // ERROR (ID 1, 3) roi WARNING (ID 2)
});

test('groupByFrame: khong co ban do van sap on dinh', () => {
  const g = L.groupByFrame([{ frame: 1, severity: 'ERROR', token: 'b', kind: 'track' }, { frame: 1, severity: 'ERROR', token: 'a', kind: 'track' }], null);
  assert.deepEqual(g[0].items.map((i) => i.token), ['a', 'b']);
});

test('filterItems', () => {
  const items = [{ severity: 'ERROR', issues: ['BOX_OFFSET'] }, { severity: 'WARNING', issues: ['BAD_SIZE', 'OVERLAP'] }];
  assert.equal(L.filterItems(items, {}).length, 2);
  assert.equal(L.filterItems(items, { severity: 'ERROR' }).length, 1);
  assert.equal(L.filterItems(items, { issue: 'OVERLAP' }).length, 1);
  assert.equal(L.filterItems(items, { severity: 'ERROR', issue: 'OVERLAP' }).length, 0);
});
