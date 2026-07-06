/* Albero cartelle ricorsivo con caricamento pigro (lazy) + matrice permessi.
   Ogni nodo viene letto dal filesystem reale al momento dell'espansione:
   nessuna struttura e' precaricata o salvata staticamente. */

let selectedPath = null;

function makeNode(name, path, hasChildren) {
  const wrapper = document.createElement("div");
  wrapper.className = "tree-node";
  wrapper.dataset.path = path;

  const row = document.createElement("div");
  row.className = "tree-row";
  row.dataset.path = path;

  const caret = document.createElement("span");
  caret.className = "tree-caret";
  caret.textContent = hasChildren ? "▶" : "";

  const icon = document.createElement("span");
  icon.textContent = "📁";

  const label = document.createElement("span");
  label.className = "truncate";
  label.textContent = name;

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

  try {
    const perm = await apiGet(`/api/permissions/${encodeURIComponent(TARGET_USERNAME)}?path=${encodeURIComponent(path)}`);
    document.getElementById("perm-read").checked = perm.read;
    document.getElementById("perm-write").checked = perm.write;
    document.getElementById("perm-delete").checked = perm.delete;

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

async function applyPermission(recursive) {
  if (selectedPath === null) return;
  const read = document.getElementById("perm-read").checked;
  const write = document.getElementById("perm-write").checked;
  const del = document.getElementById("perm-delete").checked;
  try {
    await apiPost(`/api/permissions/${encodeURIComponent(TARGET_USERNAME)}`, {
      path: selectedPath, read, write, delete: del, recursive,
    });
    toast(`Permessi aggiornati su "/${selectedPath}"${recursive ? " (ricorsivo)" : ""}.`, "success");
    await loadAssignments();
    await selectPath(selectedPath);
  } catch (err) {
    toast(err.message, "error");
  }
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
      return `<div class="flex justify-between gap-2 bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5">
        <span class="truncate">/${escapeHtml(a.path) || "(root)"}</span>
        <span class="font-mono text-indigo-400">${flags}</span>
      </div>`;
    }).join("");
  } catch (err) {
    el.innerHTML = `<p class="text-rose-400">${escapeHtml(err.message)}</p>`;
  }
}

document.getElementById("apply-recursive-btn").addEventListener("click", () => applyPermission(true));
document.getElementById("apply-single-btn").addEventListener("click", () => applyPermission(false));
document.getElementById("refresh-tree-btn").addEventListener("click", loadRoot);

loadRoot();
loadAssignments();
