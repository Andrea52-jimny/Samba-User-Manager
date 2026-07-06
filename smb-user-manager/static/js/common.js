/* Utility condivise da tutte le pagine dell'app. */

async function apiFetch(url, options = {}) {
  const opts = Object.assign({ credentials: "same-origin" }, options);
  opts.headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  const res = await fetch(url, opts);
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("Sessione scaduta");
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* no body */ }
  if (!res.ok) {
    const message = (data && data.detail) ? data.detail : `Errore HTTP ${res.status}`;
    throw new Error(message);
  }
  return data;
}

function apiGet(url) { return apiFetch(url, { method: "GET" }); }
function apiPost(url, body) { return apiFetch(url, { method: "POST", body: JSON.stringify(body || {}) }); }
function apiDelete(url) { return apiFetch(url, { method: "DELETE" }); }

function toast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) { console.log(message); return; }
  const colors = {
    info: "bg-slate-800 border-slate-600 text-slate-100",
    success: "bg-emerald-900/80 border-emerald-600 text-emerald-100",
    error: "bg-rose-900/80 border-rose-600 text-rose-100",
  };
  const el = document.createElement("div");
  el.className = `toast-enter border px-4 py-3 rounded-lg shadow-lg text-sm ${colors[type] || colors.info}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity 300ms ease";
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 320);
  }, 3200);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

async function logout() {
  try { await apiPost("/api/logout"); } catch (_) {}
  window.location.href = "/login";
}
