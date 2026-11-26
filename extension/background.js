/* Service worker: cau noi giua trang CVAT va server QC local.
 * Content script khong goi truc tiep duoc server (khac origin, CORS) nen nho service worker (co host_permissions). */
importScripts('lib.js');

const DEFAULTS = { serverUrl: 'http://127.0.0.1:8766', token: '', policy: 'conservative' };
// Chi cho phep goi cac duong dan cua server QC, khong cho content script goi URL tuy y.
const ALLOWED_PATH = /^\/(health|frames(\/\d+)?|qc)(\?.*)?$/;

async function callServer(msg) {
  if (!ALLOWED_PATH.test(msg.path || '')) return { networkError: 'Duong dan khong hop le: ' + msg.path };
  const cfg = await chrome.storage.local.get(DEFAULTS);
  const url = cfg.serverUrl.replace(/\/+$/, '') + msg.path;
  const headers = { 'X-QC-Token': cfg.token || '' };
  let body;
  if (msg.bytesB64 != null) {
    body = self.QcLib.base64ToBytes(msg.bytesB64);
    headers['Content-Type'] = 'application/octet-stream';
  } else if (msg.json != null) {
    body = JSON.stringify(msg.json);
    headers['Content-Type'] = 'application/json';
  }
  try {
    const r = await fetch(url, { method: msg.method || 'GET', headers, body });
    let json = null;
    try { json = await r.json(); } catch (e) { /* khong phai JSON */ }
    return { status: r.status, json };
  } catch (e) {
    return { networkError: `Khong ket noi duoc server QC (${cfg.serverUrl}). Da chay scripts/run_server.py chua? (${e.message})` };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg.type !== 'string') return false;
  if (msg.type === 'qc-call') {
    callServer(msg).then(sendResponse);
    return true;                       // tra loi bat dong bo
  }
  if (msg.type === 'qc-settings') {
    chrome.storage.local.get(DEFAULTS).then((cfg) => sendResponse({ policy: cfg.policy, serverUrl: cfg.serverUrl }));
    return true;
  }
  return false;
});
