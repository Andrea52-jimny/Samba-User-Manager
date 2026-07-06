/* Albero cartelle ricorsivo con caricamento pigro (lazy) + matrice permessi.
   Ogni nodo viene letto dal filesystem reale al momento dell'espansione:
   nessuna struttura e' precaricata o salvata staticamente.

   Selezione multipla: ogni riga ha una checkbox indipendente dal click sulla
   riga stessa (che serve solo per la ANTEPRIMA/focus del pannello a destra).
   Le azioni "Applica"/"Ripristina ereditarieta'" operano su TUTTE le
   cartelle spuntate, se ce n'e' almeno una; altrimenti operano solo sulla
   cartella attualmente in anteprima (comportamento invariato per il caso
   d'uso singolo). */

let selectedPath = null;           // cartella in "anteprima" nel pannello di destra
const multiSelected = new Set();   // percorsi spuntati per l'azione in blocco
const nodeCheckboxes = new Map();  // path -> elemento <input type=checkbox> (solo nodi gia' renderizzati)

function updateMultiSelectUI() {
  const countEl = document.getElementById("multi-select-count");
  const clearBtn = document.getElementById("clear-selection-btn");
  if (multiSelected.size > 0) {
    countEl.textContent = `${multiSelected.size} cartella/e selezionata/e`;
    countEl.classList.remove("hidden");
    clearBtn.disabled = false;
  } else {
    countEl.classList.add("hidden");
    clearBtn.disabled = true;
  }
  const recBtn = document.getElementById("apply-recursive-btn");
  const singleBtn = document.getElementById("apply-single-btn");
  const resetBtn = document.getElementById("reset-inherit-btn");
  if (multiSelected.size > 0) {
    recBtn.textContent = `Applica (ricorsivo) a ${multiSelected.size}`;
    singleBtn.textContent = `Applica (solo qui) a ${multiSelected.size}`;
    resetBtn.textContent = `↩ Ripristina ereditarieta' su ${multiSelected.size}`;
  } else {
    recBtn.textContent = "Applica (ricorsivo)";
    singleBtn.textContent = "Applica (solo qui)";
    resetBtn.textContent = "↩ Ripristina ereditarieta' (rimuovi assegnazione qui)";
  }
}

function toggleMultiSelect(path, checked) {
  if (checked) multiSelected.add(path);
  else multiSelected.delete(path);
  updateMultiSelectUI();
}

function clearMultiSelect() {
  multiSelected.clear();
  nodeCheckboxes.forEach(cb => { cb.checked = false; });
  updateMultiSelectUI();
}

function makeNode(name, path, hasChildren) {
  const wrapper = document.createElement("div");
  wrapper.className = "tree-node";
  wrapper.dataset.path = path;

  const row = document.createElement("div");
  row.className = "tree-row";
  row.dataset.path = path;

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.className = "w-3.5 h-3.5 rounded border-slate-600 shrink-0";
  checkbox.checked = multiSelected.has(path);
  checkbox.addEventListener("click", (e) => e.stopPropagation());
  checkbox.addEventListener("change", () => toggleMultiSelect(path, checkbox.checked));
  nodeCheckboxes.set(path, checkbox);

  const caret = document.createElement("span");
  caret.className = "tree-caret";
  caret.textContent = hasChildren ? "▶" : "";

  const icon = document.createElement("span");
  icon.textContent = "📁";

  const label = document.createElement("span");
  label.className = "truncate";
  label.textContent = name;

  row.appendChild(checkbox);
  row.appendChild(caret);
  row.appendChild(icon);
  row.appendChild(label);
  wrapper.appendChild(row);

  let childrenContainer = null;
  let loaded = false;

  async function toggleExpand() {
    if (!hasChildren) return;
    if (childrenContainer) {
      const isHidden = childrenContainer.classList.toggle("hidden");
      caret.classList.toggle("expanded", !isHidden);
      return;
    }
    caret.textContent = "⏳";
    try {
      const data = await apiGet(`/api/tree?path=${encodeURIComponent(path)}`);
      caret.textContent = "▶";
      childrenContainer = document.createElement("div");
      childrenContainer.className = "tree-children";
      data.children.forEach(child => {
        childrenContainer.appendChild(makeNode(child.name, child.path, child.has_children));
      });
      if (data.children.length === 0) {
        const empty = document.createElement("div");
        empty.className = "text-xs text-slate-600 px-2 py-1";
        empty.textContent = "(nessuna sottocartella)";
        childrenContainer.appendChild(empty);
      }
      wrapper.appendChild(childrenContainer);
      caret.classList.add("expanded");
      loaded = true;
    } catch (err) {
      caret.textContent = "▶";
      toast(err.message, "error");
    }
  }

  caret.addEventListener("click", (e) => { e.stopPropagation(); toggleExpand(); });

  row.addEventListener("click", () => {
    document.querySelectorAll(".tree-row.selected").forEach(el => el.classList.remove("selected"));
    row.classList.add("selected");
    selectPath(path);
  });

  return wrapper;
}

async function loadRoot() {
  const container = document.getElementById("tree-root");
  container.innerHTML = `<p class="text-slate-500 text-xs px-2 py-3">Caricamento cartelle radice...</p>`;
  nodeCheckboxes.clear();
  try {
    const data = await apiGet("/api/tree?path=");
    container.innerHTML = "";
    if (data.children.length === 0) {
      container.innerHTML = `<p class="text-slate-500 text-xs px-2 py-3">Nessuna cartella trovata nello share.</p>`;
      return;
    }
    data.children.forEach(child => {
      container.appendChild(makeNode(child.name, child.path, child.has_children));
    });
  } catch (err) {
    container.innerHTML = `<p class="text-rose-400 text-xs px-2 py-3">Errore caricamento albero: ${escapeHtml(err.message)}</p>`;
  }
}

async function selectPath(path) {
  selectedPath = path;
  document.getElementById("selected-path").textContent = "/" + path;
  document.getElementById("apply-recursive-btn").disabled = false;
  document.getElementById("apply-single-btn").disabled = false;
  document.getElementById("reset-inherit-btn").disabled = false;
  document.getElementById("select-children-btn").disabled = false;

  try {
    const perm = await apiGet(`/api/permissions/${encodeURIComponent(TARGET_USERNAME)}?path=${encodeURIComponent(path)}`);
    document.getElementById("perm-read").checked = perm.read;
    // "Modifica" ed "Eliminazione" sono un unico controllo in UI (vedi nota
    // in permissions.html): il bit reale di scrittura su una cartella
    // implica sempre anche la possibilita' di cancellare, quindi si mostra
    // "attivo" se ALMENO uno dei due era stato salvato (dati storici prima
    // di questa unificazione potrebbero averli distinti).
    const writeOrDelete = perm.write || perm.delete;
    document.getElementById("perm-write").checked = writeOrDelete;
    document.getElementById("perm-delete").checked = writeOrDelete;
    syncSelectAllCheckbox();

    const note = document.getElementById("inherited-note");
    if (perm.inherited_from !== null && perm.inherited_from !== undefined) {
      note.textContent = `Ereditato da: /${perm.inherited_from || "(root)"}`;
      note.classList.remove("hidden");
    } else {
      note.classList.add("hidden");
    }
  } catch (err) {
    toast(err.message, "error");
  }
}

function syncSelectAllCheckbox() {
  const r = document.getElementById("perm-read").checked;
  const w = document.getElementById("perm-write").checked;
  document.getElementById("perm-select-all").checked = r && w;
}

// "Modifica" governa anche "Eliminazione" (nascosto in UI, vedi nota in
// permissions.html): tenerli sempre sincronizzati quando l'utente clicca
// direttamente la checkbox "Modifica".
document.getElementById("perm-write").addEventListener("change", (e) => {
  document.getElementById("perm-delete").checked = e.target.checked;
});

async function selectAllSubfolders() {
  if (selectedPath === null) return;
  const btn = document.getElementById("select-children-btn");
  btn.disabled = true;
  try {
    const data = await apiGet(`/api/tree/descendants?path=${encodeURIComponent(selectedPath)}`);
    multiSelected.add(selectedPath);
    data.descendants.forEach(p => multiSelected.add(p));
    nodeCheckboxes.forEach((cb, path) => { cb.checked = multiSelected.has(path); });
    updateMultiSelectUI();
    toast(`Selezionate ${multiSelected.size} cartelle (da "/${selectedPath}" in giu').`, "success");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

async function applyPermission(recursive) {
  const read = document.getElementById("perm-read").checked;
  const write = document.getElementById("perm-write").checked;
  const del = document.getElementById("perm-delete").checked;
  const targets = multiSelected.size > 0 ? Array.from(multiSelected) : (selectedPath !== null ? [selectedPath] : []);
  if (targets.length === 0) return;

  let okCount = 0;
  for (const p of targets) {
    try {
      await apiPost(`/api/permissions/${encodeURIComponent(TARGET_USERNAME)}`, {
        path: p, read, write, delete: del, recursive,
      });
      okCount++;
    } catch (err) {
      toast(`Errore su "/${p}": ${err.message}`, "error");
    }
  }
  if (okCount > 0) {
    toast(`Permessi aggiornati su ${okCount} cartella/e${recursive ? " (ricorsivo)" : ""}.`, "success");
  }
  await loadAssignments();
  if (selectedPath !== null) await selectPath(selectedPath);
}

async function loadAssignments() {
  const el = document.getElementById("assignments-list");
  try {
    const { assignments } = await apiGet(`/api/permissions/${encodeURIComponent(TARGET_USERNAME)}/all`);
    if (assignments.length === 0) {
      el.innerHTML = `<p class="text-slate-500">Nessuna assegnazione esplicita ancora impostata.</p>`;
      return;
    }
    el.innerHTML = assignments.map(a => {
      const flags = [
        a.can_read ? "R" : "-",
        a.can_write ? "W" : "-",
        a.can_delete ? "D" : "-",
      ].join("");
      const mode = a.recursive ? "ricorsivo" : "solo qui";
      return `<div class="flex justify-between gap-2 bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5">
        <span class="truncate" title="${escapeHtml(mode)}">/${escapeHtml(a.path) || "(root)"}</span>
        <span class="flex items-center gap-1.5 shrink-0">
          <span class="text-[10px] text-slate-500">${mode}</span>
          <span class="font-mono text-indigo-400">${flags}</span>
        </span>
      </div>`;
    }).join("");
  } catch (err) {
    el.innerHTML = `<p class="text-rose-400">${escapeHtml(err.message)}</p>`;
  }
}

async function resetInherit() {
  const targets = multiSelected.size > 0 ? Array.from(multiSelected) : (selectedPath !== null ? [selectedPath] : []);
  if (targets.length === 0) return;
  const ok = confirm(
    `Rimuovere l'assegnazione esplicita di "${TARGET_USERNAME}" su ${targets.length} cartella/e?\n` +
    `Torneranno a dipendere da quanto ereditato da una cartella superiore (o da nessun accesso, se non c'e' nulla sopra).`
  );
  if (!ok) return;
  let okCount = 0;
  for (const p of targets) {
    try {
      await apiPost(`/api/permissions/${encodeURIComponent(TARGET_USERNAME)}/reset-inherit`, {
        path: p, recursive: true,
      });
      okCount++;
    } catch (err) {
      toast(`Errore su "/${p}": ${err.message}`, "error");
    }
  }
  if (okCount > 0) {
    toast(`Assegnazione rimossa su ${okCount} cartella/e.`, "success");
  }
  await loadAssignments();
  if (selectedPath !== null) await selectPath(selectedPath);
}

async function revokeAll() {
  const ok = confirm(
    `Revocare TUTTE le assegnazioni esplicite di "${TARGET_USERNAME}" su ogni cartella e sottocartella?\n` +
    `L'operazione toglie subito l'accesso su tutto lo share e non e' annullabile.`
  );
  if (!ok) return;
  try {
    await apiPost(`/api/permissions/${encodeURIComponent(TARGET_USERNAME)}/revoke-all`);
    toast(`Tutte le assegnazioni di "${TARGET_USERNAME}" sono state revocate.`, "success");
    await loadAssignments();
    if (selectedPath !== null) await selectPath(selectedPath);
  } catch (err) {
    toast(err.message, "error");
  }
}

document.getElementById("apply-recursive-btn").addEventListener("click", () => applyPermission(true));
document.getElementById("apply-single-btn").addEventListener("click", () => applyPermission(false));
document.getElementById("refresh-tree-btn").addEventListener("click", loadRoot);
document.getElementById("revoke-all-btn").addEventListener("click", revokeAll);
document.getElementById("reset-inherit-btn").addEventListener("click", resetInherit);
document.getElementById("select-children-btn").addEventListener("click", selectAllSubfolders);
document.getElementById("clear-selection-btn").addEventListener("click", clearMultiSelect);
document.getElementById("perm-select-all").addEventListener("change", (e) => {
  const checked = e.target.checked;
  document.getElementById("perm-read").checked = checked;
  document.getElementById("perm-write").checked = checked;
  document.getElementById("perm-delete").checked = checked;
});
["perm-read", "perm-write", "perm-delete"].forEach(id => {
  document.getElementById(id).addEventListener("change", syncSelectAllCheckbox);
});

loadRoot();
loadAssignments();
