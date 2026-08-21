/**
 * Kein Build-Schritt, kein Frontend-Framework: reines, abhaengigkeitsfreies
 * JavaScript reicht fuer dieses Grundgerüst (Liste laden, filtern,
 * Checkboxen verwalten, mailto-Link bauen). Das haelt den Container klein
 * und den Einstieg fuer das Team niedrig - siehe README fuer die Abwaegung.
 *
 * Die API liefert bewusst maximal MAX_PAGE_SIZE (Server: 500) Ergebnisse pro
 * Aufruf zurueck, damit niemand versehentlich (oder absichtlich) den
 * gesamten Datensatz in einem Request abziehen kann. Bei > PAGE_SIZE
 * Treffern wird das im UI kommuniziert ("Suche verfeinern").
 */
const PAGE_SIZE = 200;

const state = {
  search: "",
  bundesland: "",
  angebot: "",
  // Auswahl bleibt ueber Filteraenderungen hinweg erhalten (Map: id -> {name, email}).
  selected: new Map(),
};

const els = {
  search: document.getElementById("search"),
  bundeslandFilter: document.getElementById("bundesland-filter"),
  angebotFilter: document.getElementById("angebot-filter"),
  list: document.getElementById("center-list"),
  resultCount: document.getElementById("result-count"),
  selectedCount: document.getElementById("selected-count"),
  sendMail: document.getElementById("send-mail"),
  selectAll: document.getElementById("select-all"),
  selectNone: document.getElementById("select-none"),
};

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

async function loadBundeslaender() {
  const res = await fetch("/api/bundeslaender");
  if (!res.ok) return;
  const values = await res.json();
  for (const v of values) {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    els.bundeslandFilter.appendChild(opt);
  }
}

function buildQuery() {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (state.search) params.set("search", state.search);
  if (state.bundesland) params.set("bundesland", state.bundesland);
  if (state.angebot) params.set("angebot", state.angebot);
  return params.toString();
}

async function loadCenters() {
  els.resultCount.textContent = "Lade Daten …";
  const res = await fetch(`/api/centers?${buildQuery()}`);
  if (!res.ok) {
    els.resultCount.textContent = "Fehler beim Laden der Daten.";
    return;
  }
  const data = await res.json();
  renderList(data.items, data.total);
}

function renderList(items, total) {
  els.list.innerHTML = "";

  if (total > items.length) {
    els.resultCount.textContent = `${items.length} von ${total} Treffern angezeigt – Suche verfeinern, um mehr zu sehen.`;
  } else {
    els.resultCount.textContent = `${total} Treffer`;
  }

  for (const center of items) {
    const li = document.createElement("li");
    li.className = "center-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = `center-${center.id}`;
    checkbox.checked = state.selected.has(center.id);
    checkbox.disabled = !center.email;
    checkbox.addEventListener("change", () => toggleSelection(center, checkbox.checked));

    const label = document.createElement("label");
    label.setAttribute("for", checkbox.id);

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = center.name;

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = [center.plz, center.ort, center.bundesland].filter(Boolean).join(" · ");

    label.appendChild(name);
    label.appendChild(meta);

    if (!center.email) {
      const noEmail = document.createElement("div");
      noEmail.className = "no-email";
      noEmail.textContent = "Keine E-Mail-Adresse hinterlegt – kann nicht ausgewählt werden.";
      label.appendChild(noEmail);
    }

    li.appendChild(checkbox);
    li.appendChild(label);
    els.list.appendChild(li);
  }

  updateSelectedUi();
}

function toggleSelection(center, isSelected) {
  if (isSelected) {
    state.selected.set(center.id, { name: center.name, email: center.email });
  } else {
    state.selected.delete(center.id);
  }
  updateSelectedUi();
}

function updateSelectedUi() {
  els.selectedCount.textContent = String(state.selected.size);
  els.sendMail.disabled = state.selected.size === 0;
}

function selectAllVisible() {
  els.list.querySelectorAll('input[type="checkbox"]:not(:disabled)').forEach((cb) => {
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));
  });
}

function clearSelection() {
  state.selected.clear();
  els.list.querySelectorAll('input[type="checkbox"]').forEach((cb) => (cb.checked = false));
  updateSelectedUi();
}

function sendMail() {
  const emails = [...state.selected.values()].map((c) => c.email).filter(Boolean);
  if (emails.length === 0) return;

  // Hinweis: mailto: hat keine garantierte Laengenbegrenzung, in der Praxis
  // sind aber ca. 1800-2000 Zeichen (Outlook) ein realistisches Limit.
  // Bei sehr grossen Auswahlen sollte das Team spaeter eine Warnung/Split
  // ergaenzen - siehe README, "Bekannte Einschraenkungen".
  const bcc = encodeURIComponent(emails.join(","));
  const subject = encodeURIComponent("Anfrage Pflege-/Beratungsstelle");
  window.location.href = `mailto:?bcc=${bcc}&subject=${subject}`;
}

els.search.addEventListener(
  "input",
  debounce((e) => {
    state.search = e.target.value.trim();
    loadCenters();
  }, 300)
);
els.bundeslandFilter.addEventListener("change", (e) => {
  state.bundesland = e.target.value;
  loadCenters();
});
els.angebotFilter.addEventListener("change", (e) => {
  state.angebot = e.target.value;
  loadCenters();
});
els.selectAll.addEventListener("click", selectAllVisible);
els.selectNone.addEventListener("click", clearSelection);
els.sendMail.addEventListener("click", sendMail);

loadBundeslaender();
loadCenters();
