const username = document.body.dataset.username;
const treeRoot = document.getElementById("tree-root");
const template = document.getElementById("tree-node-template");
const recursiveToggle = document.getElementById("recursive-toggle");

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

function buildNodeElement(node) {
  const li = template.content.firstElementChild.cloneNode(true);
  li.dataset.relpath = node.rel_path;
  li.dataset.loaded = "false";

  const toggleBtn = li.querySelector(".sm-tree-toggle");
  li.querySelector(".sm-tree-name").textContent = node.name;

  if (!node.has_children) {
    toggleBtn.classList.add("leaf");
  }

  // Carica lo stato corrente dei permessi (letto live via getfacl)
  apiFetch(`/api/permissions?username=${encodeURIComponent(username)}&path=${encodeURIComponent(node.rel_path)}`)
    .then((perm) => {
      li.querySelector(".perm-read").checked = !!perm.read;
      li.querySelector(".perm-write").checked = !!perm.write;
      li.querySelector(".perm-delete").checked = !!perm.delete;
    })
    .catch(() => {});

  return li;
}

async function loadChildren(relPath, ulElement) {
  ulElement.innerHTML = `<li class="px-3 py-2 text-xs sm-text-muted">Caricamento...</li>`;
  try {
    const { nodes } = await apiFetch(`/api/tree?path=${encodeURIComponent(relPath)}`);
    ulElement.innerHTML = "";
    if (nodes.length === 0) {
      ulElement.innerHTML = `<li class="px-3 py-2 text-xs sm-text-muted">Nessuna sottocartella</li>`;
      return;
    }
    for (const node of nodes) {
      ulElement.appendChild(buildNodeElement(node));
    }
  } catch (err) {
    ulElement.innerHTML = `<li class="px-3 py-2 text-xs text-rose-400">${err.message}</li>`;
  }
}

treeRoot.addEventListener("click", async (e) => {
  const toggleBtn = e.target.closest(".sm-tree-toggle");
  if (!toggleBtn || toggleBtn.classList.contains("leaf")) return;

  const li = toggleBtn.closest(".sm-tree-node");
  const childUl = li.querySelector(":scope > .sm-tree-children");
  const isOpen = toggleBtn.classList.contains("open");

  if (isOpen) {
    toggleBtn.classList.remove("open");
    childUl.classList.add("hidden");
    return;
  }

  toggleBtn.classList.add("open");
  childUl.classList.remove("hidden");

  if (li.dataset.loaded !== "true") {
    li.dataset.loaded = "true";
    await loadChildren(li.dataset.relpath, childUl);
  }
});

treeRoot.addEventListener("change", async (e) => {
  const checkbox = e.target.closest(".perm-read, .perm-write, .perm-delete");
  if (!checkbox) return;

  const li = checkbox.closest(".sm-tree-node");
  const relPath = li.dataset.relpath;
  const readCb = li.querySelector(".perm-read");
  const writeCb = li.querySelector(".perm-write");
  const deleteCb = li.querySelector(".perm-delete");

  const payload = {
    username,
    path: relPath,
    read: readCb.checked,
    write: writeCb.checked,
    delete: deleteCb.checked,
    recursive: recursiveToggle.checked,
  };

  [readCb, writeCb, deleteCb].forEach((cb) => (cb.disabled = true));
  try {
    await apiFetch("/api/permissions", { method: "POST", body: JSON.stringify(payload) });
  } catch (err) {
    // rollback visivo in caso di errore
    checkbox.checked = !checkbox.checked;
    alert(`Errore applicando il permesso: ${err.message}`);
  } finally {
    [readCb, writeCb, deleteCb].forEach((cb) => (cb.disabled = false));
  }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  await apiFetch("/api/logout", { method: "POST" });
  window.location.href = "/login";
});

// Carica le cartelle root all'avvio
loadChildren("", treeRoot);
