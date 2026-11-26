const DEFAULTS = { serverUrl: 'http://127.0.0.1:8766', token: '', policy: 'conservative' };
const $ = (id) => document.getElementById(id);

function show(msg, cls) {
  const el = $('status');
  el.textContent = msg;
  el.className = cls || '';
}

async function load() {
  const cfg = await chrome.storage.local.get(DEFAULTS);
  $('serverUrl').value = cfg.serverUrl;
  $('token').value = cfg.token;
  $('policy').value = cfg.policy;
}

async function save() {
  const serverUrl = $('serverUrl').value.trim() || DEFAULTS.serverUrl;
  if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/.test(serverUrl)) {
    show('Địa chỉ phải là http://127.0.0.1:PORT hoặc http://localhost:PORT (server chỉ chạy trên máy này).', 'bad');
    return false;
  }
  await chrome.storage.local.set({ serverUrl, token: $('token').value.trim(), policy: $('policy').value });
  show('Đã lưu.', 'ok');
  return true;
}

async function test() {
  if (!(await save())) return;
  show('Đang kiểm tra...');
  const h = await chrome.runtime.sendMessage({ type: 'qc-call', method: 'GET', path: '/health' });
  if (h.networkError) return show(h.networkError, 'bad');
  if (h.status !== 200) return show('Server trả về HTTP ' + h.status, 'bad');
  const f = await chrome.runtime.sendMessage({ type: 'qc-call', method: 'GET', path: '/frames?job=ping' });
  if (f.status === 401) return show('Server chạy (phiên bản ' + h.json.version + ') nhưng TOKEN SAI.', 'bad');
  show('Kết nối tốt. Server QC phiên bản ' + h.json.version + ', ' + h.json.classes.length + ' class tham chiếu.' +
       (h.json.meta_frames ? '\nCó ego pose cho ' + h.json.meta_frames + ' frame.' : '\nKhông có ego pose: bỏ qua kiểm tra hướng ngược.'), 'ok');
}

$('save').addEventListener('click', save);
$('test').addEventListener('click', test);
load();
