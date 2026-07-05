const tbody = document.getElementById("users-tbody");

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function formatDate(iso) {
  if (!iso) return "Nessuna scadenza";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("it-IT", { year: "numeric", month: "short", day: "2-digit" });
}

async function apiFetch(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("Sessione scaduta");
  }
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json() : null;
  if (!res.ok) throw new Error((data && data.detail) || "Errore imprevisto");
  return data;
}

function renderRow(user) {
  const isSuspended = !!user.is_suspended;
  return `
    <tr>
      <td class="px-4 py-3">
        <a href="/permissions/${encodeURIComponent(user.username)}" class="sm-code hover:text-emerald-400">${escapeHtml(user.username)}</a>
      </td>
      <td class="px-4 py-3 sm-text-muted">${formatDate(user.expiry_date)}</td>
      <td class="px-4 py-3">
        ${isSuspended
          ? `<span class="sm-pill sm-pill-suspended"><span class="sm-pill-dot"></span>Sospeso</span>`
          : `<span class="sm-pill sm-pill-active"><span class="sm-pill-dot"></span>Attivo</span>`}
      </td>
      <td class="px-4 py-3">
        <div class="flex justify-end gap-2">
          <button class="sm-btn-icon warn" data-action="suspend" data-username="${escapeHtml(user.username)}" title="${isSuspended ? 'Riattiva' : 'Sospendi'}">
            ${isSuspended ? "▶️" : "⏸️"}
          </button>
          <button class="sm-btn-icon" data-action="reset" data-username="${escapeHtml(user.username)}" title="Reset password">🔑</button>
          <button class="sm-btn-icon danger" data-action="delete" data-username="${escapeHtml(user.username)}" title="Elimina definitivamente">🗑️</button>
        </div>
      </td>
    </tr>`;
}

async function loadUsers() {
  try {
    const { users } = await apiFetch("/api/users");
    tbody.innerHTML = users.length
      ? users.map(renderRow).join("")
      : `<tr><td colspan="4" class="px-4 py-6 text-center sm-text-muted">Nessun utente gestito. Creane uno dal pannello a destra.</td></tr>`;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="px-4 py-6 text-center text-rose-400">${err.message}</td></tr>`;
  }
}

tbody.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const { action, username } = btn.dataset;

  if (action === "suspend") {
    btn.disabled = true;
    try {
      await apiFetch(`/api/users/${encodeURIComponent(username)}/suspend`, { method: "POST" });
      await loadUsers();
    } catch (err) {
      alert(err.message);
    }
  } else if (action === "reset") {
    openResetModal(username);
  } else if (action === "delete") {
    if (!confirm(`Eliminare definitivamente l'utente "${username}"?\nQuesta azione rimuove l'account Linux, Samba e tutte le ACL associate. Non è reversibile.`)) return;
    btn.disabled = true;
    try {
      await apiFetch(`/api/users/${encodeURIComponent(username)}`, { method: "DELETE" });
      await loadUsers();
    } catch (err) {
      alert(err.message);
    }
  }
});

// --- Creazione utente ---

const noExpiryCheckbox = document.getElementById("no-expiry");
const expiryWrapper = document.getElementById("expiry-wrapper");
noExpiryCheckbox.addEventListener("change", () => {
  expiryWrapper.classList.toggle("hidden", noExpiryCheckbox.checked);
});

document.getElementById("create-user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorBox = document.getElementById("create-error");
  errorBox.classList.add("hidden");

  const payload = {
    username: document.getElementById("new-username").value.trim(),
    password: document.getElementById("new-password").value,
    no_expiry: noExpiryCheckbox.checked,
    expiry_date: noExpiryCheckbox.checked ? null : document.getElementById("expiry-date").value,
  };

  try {
    await apiFetch("/api/users", { method: "POST", body: JSON.stringify(payload) });
    e.target.reset();
    noExpiryCheckbox.checked = true;
    expiryWrapper.classList.add("hidden");
    await loadUsers();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.classList.remove("hidden");
  }
});

// --- Modale reset password ---

const resetModal = document.getElementById("reset-modal");
let resetTargetUsername = null;

function openResetModal(username) {
  resetTargetUsername = username;
  document.getElementById("reset-username").textContent = username;
  document.getElementById("reset-new-password").value = "";
  document.getElementById("reset-error").classList.add("hidden");
  resetModal.classList.remove("hidden");
}

document.getElementById("reset-cancel").addEventListener("click", () => resetModal.classList.add("hidden"));

document.getElementById("reset-confirm").addEventListener("click", async () => {
  const newPassword = document.getElementById("reset-new-password").value;
  const errorBox = document.getElementById("reset-error");
  if (newPassword.length < 8) {
    errorBox.textContent = "La password deve avere almeno 8 caratteri.";
    errorBox.classList.remove("hidden");
    return;
  }
  try {
    await apiFetch(`/api/users/${encodeURIComponent(resetTargetUsername)}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    });
    resetModal.classList.add("hidden");
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.classList.remove("hidden");
  }
});

// --- Avviso configurazione Samba (force user) ---

async function checkSmbStatus() {
  try {
    const status = await apiFetch("/api/smb-status");
    document.getElementById("smb-warning").classList.toggle("hidden", !status.force_user_active);
  } catch (err) {
    // silenzioso: non bloccare il resto della dashboard per questo controllo
  }
}

document.getElementById("fix-smb-btn").addEventListener("click", async (e) => {
  e.target.disabled = true;
  e.target.textContent = "Applicazione in corso...";
  try {
    await apiFetch("/api/smb-fix", { method: "POST" });
    await checkSmbStatus();
  } catch (err) {
    alert(err.message);
  } finally {
    e.target.disabled = false;
    e.target.textContent = "Correggi automaticamente";
  }
});

// --- Logout ---

document.getElementById("logout-btn").addEventListener("click", async () => {
  await apiFetch("/api/logout", { method: "POST" });
  window.location.href = "/login";
});

loadUsers();
checkSmbStatus();
