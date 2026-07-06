/* Logica della dashboard: elenco utenti, creazione, sospensione, reset,
   eliminazione, stato configurazione Samba, log attivita'. */

function closeModal(id) { document.getElementById(id).classList.add("hidden"); }
function openModal(id) { document.getElementById(id).classList.remove("hidden"); }

function statusBadge(user) {
  if (user.suspended) {
    return `<span class="badge-pill bg-rose-500/15 text-rose-300 border border-rose-500/30">🚫 Sospeso</span>`;
  }
  if (user.expired) {
    return `<span class="badge-pill bg-amber-500/15 text-amber-300 border border-amber-500/30">⏳ Scaduto</span>`;
  }
  return `<span class="badge-pill bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">✅ Attivo</span>`;
}

// expiry_date e' salvata come "YYYY-MM-DDTHH:MM" (data e ora); qui la
// mostriamo in formato leggibile "GG/MM/AAAA HH:MM".
function formatExpiry(expiryDate) {
  if (!expiryDate) return "Infinita";
  const [datePart, timePart] = expiryDate.split("T");
  const [y, m, d] = datePart.split("-");
  return `${d}/${m}/${y}${timePart ? " " + timePart : ""}`;
}

function randomPassword() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%";
  let pw = "";
  for (let i = 0; i < 14; i++) pw += chars[Math.floor(Math.random() * chars.length)];
  return pw;
}

async function loadUsers() {
  const { users } = await apiGet("/api/users");
  const tbody = document.getElementById("users-tbody");
  const empty = document.getElementById("users-empty");
  document.getElementById("user-count").textContent = `${users.length} utente/i`;

  if (users.length === 0) {
    tbody.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  tbody.innerHTML = users.map(u => `
    <tr class="hover:bg-slate-800/40 transition">
      <td class="px-5 py-3">
        <a href="/permissions/${encodeURIComponent(u.username)}" class="font-medium text-indigo-400 hover:text-indigo-300">${escapeHtml(u.username)}</a>
      </td>
      <td class="px-5 py-3">${statusBadge(u)}</td>
      <td class="px-5 py-3 text-slate-400">${formatExpiry(u.expiry_date)}</td>
      <td class="px-5 py-3">
        <div class="flex items-center justify-end gap-1.5">
          <a href="/permissions/${encodeURIComponent(u.username)}" title="Gestisci permessi"
             class="w-8 h-8 flex items-center justify-center rounded-lg border border-slate-700 hover:bg-slate-800">🔑</a>
          <button title="${u.suspended ? 'Riattiva' : 'Sospendi'}" data-action="toggle-suspend" data-username="${escapeHtml(u.username)}" data-suspended="${u.suspended}"
             class="w-8 h-8 flex items-center justify-center rounded-lg border border-slate-700 hover:bg-slate-800">${u.suspended ? "▶️" : "⏸️"}</button>
          <button title="Reset password" data-action="reset" data-username="${escapeHtml(u.username)}"
             class="w-8 h-8 flex items-center justify-center rounded-lg border border-slate-700 hover:bg-slate-800">🔄</button>
          <button title="Modifica scadenza" data-action="edit-expiry" data-username="${escapeHtml(u.username)}" data-expiry="${escapeHtml(u.expiry_date || '')}"
             class="w-8 h-8 flex items-center justify-center rounded-lg border border-slate-700 hover:bg-slate-800">📅</button>
          <button title="Copia utente (clona permessi)" data-action="clone" data-username="${escapeHtml(u.username)}"
             class="w-8 h-8 flex items-center justify-center rounded-lg border border-slate-700 hover:bg-slate-800">📋</button>
          <button title="Elimina definitivamente" data-action="delete" data-username="${escapeHtml(u.username)}"
             class="w-8 h-8 flex items-center justify-center rounded-lg border border-rose-800/60 text-rose-400 hover:bg-rose-900/40">🗑️</button>
        </div>
      </td>
    </tr>
  `).join("");
}

async function loadAudit() {
  try {
    const { entries } = await apiGet("/api/audit?limit=20");
    const list = document.getElementById("audit-list");
    if (entries.length === 0) {
      list.innerHTML = `<li class="px-5 py-4 text-slate-500">Nessuna attivita' registrata.</li>`;
      return;
    }
    list.innerHTML = entries.map(e => `
      <li class="px-5 py-2.5 flex justify-between gap-3">
        <span class="text-slate-300">${escapeHtml(e.action)}${e.target ? " &middot; " + escapeHtml(e.target) : ""}</span>
        <span class="text-slate-600 whitespace-nowrap">${escapeHtml(e.timestamp)}</span>
      </li>
    `).join("");
  } catch (_) { /* non bloccante */ }
}

async function loadSmbStatus() {
  const el = document.getElementById("smbconf-status");
  const patchBtn = document.getElementById("patch-smbconf-btn");
  try {
    const status = await apiGet("/api/system/smbconf-status");
    let html = "";
    if (status.force_user_present) {
      html += `<p class="text-rose-400">⚠️ "force user" ancora attivo: le ACL per-utente NON sono efficaci.</p>`;
      patchBtn.classList.remove("hidden");
    } else {
      html += `<p class="text-emerald-400">✅ "force user" rimosso, ACL per-utente attive.</p>`;
      patchBtn.classList.add("hidden");
    }
    if (status.valid_users_line) {
      html += `<p class="text-slate-500 mt-1">${escapeHtml(status.valid_users_line)}</p>`;
    }
    if (status.zfs_warning) {
      html += `<p class="text-amber-400 mt-2">${escapeHtml(status.zfs_warning)}</p>`;
    }
    el.innerHTML = html;
  } catch (err) {
    el.innerHTML = `<p class="text-slate-500">Stato non disponibile: ${escapeHtml(err.message)}</p>`;
  }
}

// --- Creazione utente ---
document.getElementById("infinite-checkbox").addEventListener("change", (e) => {
  document.getElementById("expiry-date-input").disabled = e.target.checked;
});

document.getElementById("gen-password-btn").addEventListener("click", () => {
  document.getElementById("new-password").value = randomPassword();
});

document.getElementById("create-user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const infinite = document.getElementById("infinite-checkbox").checked;
  try {
    await apiPost("/api/users", {
      username: form.username.value.trim().toLowerCase(),
      password: form.password.value,
      infinite,
      expiry_date: infinite ? null : form.expiry_date.value,
    });
    toast(`Utente "${form.username.value}" creato con successo.`, "success");
    form.reset();
    document.getElementById("infinite-checkbox").checked = true;
    document.getElementById("expiry-date-input").disabled = true;
    await loadUsers();
    await loadAudit();
  } catch (err) {
    toast(err.message, "error");
  }
});

// --- Azioni sulla tabella (delegate) ---
let pendingUsername = null;

document.getElementById("users-tbody").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const action = btn.dataset.action;
  const username = btn.dataset.username;

  if (action === "toggle-suspend") {
    const suspended = btn.dataset.suspended === "1" || btn.dataset.suspended === "true";
    try {
      await apiPost(`/api/users/${encodeURIComponent(username)}/${suspended ? "resume" : "suspend"}`);
      toast(`Utente "${username}" ${suspended ? "riattivato" : "sospeso"}.`, "success");
      await loadUsers();
      await loadAudit();
    } catch (err) { toast(err.message, "error"); }
  }

  if (action === "reset") {
    pendingUsername = username;
    document.getElementById("reset-username").textContent = username;
    document.getElementById("reset-password-input").value = "";
    openModal("reset-modal");
  }

  if (action === "delete") {
    pendingUsername = username;
    document.getElementById("delete-username").textContent = username;
    openModal("delete-modal");
  }

  if (action === "edit-expiry") {
    pendingUsername = username;
    const currentExpiry = btn.dataset.expiry || "";
    document.getElementById("expiry-username").textContent = username;
    const infiniteCb = document.getElementById("expiry-infinite-checkbox");
    const input = document.getElementById("expiry-modal-input");
    infiniteCb.checked = !currentExpiry;
    input.disabled = !currentExpiry;
    input.value = currentExpiry;
    openModal("expiry-modal");
  }

  if (action === "clone") {
    pendingUsername = username;
    document.getElementById("clone-source-username").textContent = username;
    document.getElementById("clone-username-input").value = "";
    document.getElementById("clone-password-input").value = randomPassword();
    document.getElementById("clone-infinite-checkbox").checked = true;
    document.getElementById("clone-expiry-input").disabled = true;
    document.getElementById("clone-expiry-input").value = "";
    openModal("clone-modal");
  }
});

document.getElementById("expiry-infinite-checkbox").addEventListener("change", (e) => {
  document.getElementById("expiry-modal-input").disabled = e.target.checked;
});

document.getElementById("expiry-confirm-btn").addEventListener("click", async () => {
  const infinite = document.getElementById("expiry-infinite-checkbox").checked;
  const expiryValue = document.getElementById("expiry-modal-input").value;
  if (!infinite && !expiryValue) { toast("Seleziona una data e ora di scadenza.", "error"); return; }
  try {
    await apiPost(`/api/users/${encodeURIComponent(pendingUsername)}/expiry`, {
      infinite, expiry_date: infinite ? null : expiryValue,
    });
    toast(`Scadenza aggiornata per "${pendingUsername}".`, "success");
    closeModal("expiry-modal");
    await loadUsers();
    await loadAudit();
  } catch (err) { toast(err.message, "error"); }
});

document.getElementById("clone-gen-password-btn").addEventListener("click", () => {
  document.getElementById("clone-password-input").value = randomPassword();
});

document.getElementById("clone-infinite-checkbox").addEventListener("change", (e) => {
  document.getElementById("clone-expiry-input").disabled = e.target.checked;
});

document.getElementById("clone-confirm-btn").addEventListener("click", async () => {
  const newUsername = document.getElementById("clone-username-input").value.trim().toLowerCase();
  const password = document.getElementById("clone-password-input").value;
  const infinite = document.getElementById("clone-infinite-checkbox").checked;
  const expiryValue = document.getElementById("clone-expiry-input").value;
  if (!newUsername) { toast("Inserisci un username per il nuovo utente.", "error"); return; }
  if (password.length < 8) { toast("La password deve avere almeno 8 caratteri.", "error"); return; }
  if (!infinite && !expiryValue) { toast("Seleziona una data e ora di scadenza, oppure spunta 'durata infinita'.", "error"); return; }
  try {
    const result = await apiPost(`/api/users/${encodeURIComponent(pendingUsername)}/clone`, {
      new_username: newUsername, password, infinite,
      expiry_date: infinite ? null : expiryValue,
    });
    toast(`Utente "${newUsername}" creato con ${result.copied_permissions} assegnazione/i copiate da "${pendingUsername}".`, "success");
    closeModal("clone-modal");
    await loadUsers();
    await loadAudit();
  } catch (err) { toast(err.message, "error"); }
});

document.getElementById("reset-confirm-btn").addEventListener("click", async () => {
  const password = document.getElementById("reset-password-input").value;
  if (password.length < 8) { toast("La password deve avere almeno 8 caratteri.", "error"); return; }
  try {
    await apiPost(`/api/users/${encodeURIComponent(pendingUsername)}/reset-password`, { password });
    toast(`Password reimpostata per "${pendingUsername}".`, "success");
    closeModal("reset-modal");
    await loadAudit();
  } catch (err) { toast(err.message, "error"); }
});

document.getElementById("delete-confirm-btn").addEventListener("click", async () => {
  try {
    await apiDelete(`/api/users/${encodeURIComponent(pendingUsername)}`);
    toast(`Utente "${pendingUsername}" eliminato.`, "success");
    closeModal("delete-modal");
    await loadUsers();
    await loadAudit();
  } catch (err) { toast(err.message, "error"); }
});

// --- Configurazione Samba ---
document.getElementById("patch-smbconf-btn").addEventListener("click", async () => {
  if (!confirm("Verra' modificato /etc/samba/smb.conf (con backup automatico) e ricaricato Samba. Continuare?")) return;
  try {
    await apiPost("/api/system/patch-smbconf");
    toast("Configurazione Samba aggiornata correttamente.", "success");
    await loadSmbStatus();
    await loadAudit();
  } catch (err) { toast(err.message, "error"); }
});

// --- Cambio password admin ---
document.getElementById("change-pwd-btn").addEventListener("click", () => {
  document.getElementById("current-pwd-input").value = "";
  document.getElementById("new-pwd-input").value = "";
  openModal("change-pwd-modal");
});
document.getElementById("change-pwd-confirm-btn").addEventListener("click", async () => {
  try {
    await apiPost("/api/admin/change-password", {
      current_password: document.getElementById("current-pwd-input").value,
      new_password: document.getElementById("new-pwd-input").value,
    });
    toast("Password amministratore aggiornata.", "success");
    closeModal("change-pwd-modal");
  } catch (err) { toast(err.message, "error"); }
});

// --- Init ---
loadUsers();
loadAudit();
loadSmbStatus();
setInterval(loadUsers, 30000);
