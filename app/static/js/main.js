/**
 * Pflegezentren-Finder – Oberfläche (ohne Build-Schritt, ohne Framework).
 *
 * Ansichten: Übersicht, Einrichtungen, Datenpflege (nur editor/admin),
 * E-Mail-Zentrale, Versandhistorie. Die Rechte prüft der Server
 * (require_permission); data-can-edit blendet nur Bedienelemente aus.
 *
 * Kein innerHTML mit Daten aus der API: alle Texte über textContent,
 * damit eingeschleuster HTML-Code nie ausgeführt wird (siehe CSP).
 */
"use strict";

const PAGE_SIZE = 50;
const MAIL_BATCH_SIZE = 20;
const MAILTO_WARN_LENGTH = 1900;
const MANUAL_ID_START = 1000000;

const OFFERS = {
  pflegestuetzpunkt: "Pflegestützpunkt",
  pflegeberatung: "Pflegeberatung",
  wohnberatung: "Wohnberatung",
  demenzberatung: "Demenzberatung",
  angehoerigenberatung: "Angehörigenberatung",
  betreuungsberatung: "Betreuungsberatung",
};

const LAENDER = {
  BW: "Baden-Württemberg", BY: "Bayern", BE: "Berlin", BB: "Brandenburg",
  HB: "Bremen", HH: "Hamburg", HE: "Hessen", MV: "Mecklenburg-Vorpommern",
  NI: "Niedersachsen", NW: "Nordrhein-Westfalen", RP: "Rheinland-Pfalz",
  SL: "Saarland", SN: "Sachsen", ST: "Sachsen-Anhalt",
  SH: "Schleswig-Holstein", TH: "Thüringen",
};

const VIEWS = {
  dashboard: { title: "Übersicht", desc: "Kennzahlen und Schnellzugriff." },
  einrichtungen: { title: "Einrichtungen", desc: "Pflegeeinrichtungen finden, filtern und verwalten." },
  datenpflege: { title: "Datenpflege", desc: "Einrichtungen anlegen, bearbeiten oder deaktivieren." },
  email: { title: "E-Mail-Zentrale", desc: "Nachrichten an ausgewählte Einrichtungen vorbereiten." },
  historie: { title: "Versandhistorie", desc: "Dokumentierte Versandvorgänge nachvollziehen." },
};

const canEdit = document.body.dataset.canEdit === "true";
const $ = (id) => document.getElementById(id);

const state = {
  search: "",
  angebot: "",
  bundesland: "",
  offset: 0,
  total: 0,
  items: [],
  // Auswahl bleibt über Filter und Seiten hinweg erhalten: id -> {name, email}
  selected: new Map(),
  editing: null,
};

/* ------------------------------------------------------------------ */
/* Hilfsfunktionen                                                     */
/* ------------------------------------------------------------------ */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function landName(code) {
  return LAENDER[code] || code || "";
}

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

function formatApiError(detail) {
  if (!detail) return "Unbekannter Fehler.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => `${(d.loc || []).slice(-1)[0] || "Feld"}: ${d.msg || "ungültig"}`)
      .join(" · ");
  }
  return String(detail);
}

/**
 * fetch-Wrapper. Ist die Sitzung abgelaufen, leitet der Server auf den
 * Login um und liefert HTML statt JSON – dann Seite neu laden (-> Login).
 */
async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: options.body ? { "Content-Type": "application/json" } : {},
    ...options,
  });
  const type = res.headers.get("content-type") || "";
  if (res.redirected || (res.status !== 204 && !type.includes("application/json"))) {
    window.location.reload();
    throw new Error("Sitzung abgelaufen – bitte erneut anmelden.");
  }
  if (res.status === 204) return null;
  const data = await res.json();
  if (!res.ok) {
    if (res.status === 403) throw new Error("Keine Berechtigung für diese Aktion.");
    throw new Error(formatApiError(data.detail));
  }
  return data;
}

function setMessage(node, text, kind) {
  node.textContent = text || "";
  node.classList.remove("is-error", "is-success");
  if (kind) node.classList.add(kind === "error" ? "is-error" : "is-success");
}

/* ------------------------------------------------------------------ */
/* Ansichten                                                           */
/* ------------------------------------------------------------------ */

function showView(name) {
  if (!VIEWS[name] || (name === "datenpflege" && !canEdit)) name = "einrichtungen";

  document.querySelectorAll(".page-view").forEach((view) => {
    view.hidden = view.id !== `view-${name}`;
  });
  document.querySelectorAll(".nav-link").forEach((link) => {
    const active = link.dataset.view === name;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });

  $("breadcrumb-current").textContent = VIEWS[name].title;
  $("page-title").textContent = VIEWS[name].title;
  $("page-description").textContent = VIEWS[name].desc;

  if (window.location.hash !== `#${name}`) {
    history.replaceState(null, "", `#${name}`);
  }
  if (name === "email") renderEmailRecipients();
  window.scrollTo(0, 0);
}

/* ------------------------------------------------------------------ */
/* Einrichtungen                                                       */
/* ------------------------------------------------------------------ */

async function loadBundeslaender() {
  const filter = $("region-filter");
  try {
    const codes = await api("/api/bundeslaender");
    for (const code of codes) {
      const opt = el("option", null, landName(code));
      opt.value = code;
      filter.appendChild(opt);
    }
  } catch {
    /* Filter bleibt dann leer; die Liste funktioniert trotzdem. */
  }

  const formSelect = $("center-state");
  if (formSelect) {
    for (const [code, name] of Object.entries(LAENDER)) {
      const opt = el("option", null, name);
      opt.value = code;
      formSelect.appendChild(opt);
    }
  }
}

function buildQuery() {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(state.offset) });
  if (state.search) params.set("search", state.search);
  if (state.angebot) params.set("angebot", state.angebot);
  if (state.bundesland) params.set("bundesland", state.bundesland);
  return params.toString();
}

async function loadCenters() {
  $("results-count").textContent = "Einrichtungen werden geladen ...";
  try {
    const data = await api(`/api/centers?${buildQuery()}`);
    state.items = data.items;
    state.total = data.total;
    renderResults();
  } catch (error) {
    $("directory-results").replaceChildren(el("p", "empty-state", `Fehler beim Laden: ${error.message}`));
    $("results-count").textContent = "Keine Daten verfügbar.";
  }
}

function renderResults() {
  const box = $("directory-results");
  box.replaceChildren();

  const from = state.total ? state.offset + 1 : 0;
  const to = state.offset + state.items.length;
  $("results-count").textContent = state.total
    ? `${state.total.toLocaleString("de-DE")} Einrichtungen gefunden · angezeigt ${from}–${to}`
    : "Keine Einrichtungen gefunden.";

  if (!state.items.length) {
    box.appendChild(el("p", "empty-state", "Keine Treffer. Passe die Suche oder die Filter an."));
  }
  for (const center of state.items) box.appendChild(renderCard(center));

  const page = Math.floor(state.offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
  $("pagination-info").textContent = `Seite ${page} von ${pages}`;
  $("previous-page").disabled = state.offset === 0;
  $("next-page").disabled = state.offset + PAGE_SIZE >= state.total;
}

function renderCard(center) {
  const card = el("article", "directory-card");

  const select = el("label", "card-select");
  const checkbox = el("input");
  checkbox.type = "checkbox";
  checkbox.checked = state.selected.has(center.id);
  checkbox.disabled = !center.email;
  checkbox.setAttribute("aria-label", `${center.name || "Einrichtung"} auswählen`);
  checkbox.addEventListener("change", () => toggleSelection(center, checkbox.checked));
  select.appendChild(checkbox);
  card.appendChild(select);

  const body = el("div", "card-body");
  body.appendChild(el("h3", null, center.name || "(ohne Namen)"));

  const place = [center.adresse, [center.plz, center.ort].filter(Boolean).join(" "), landName(center.bundesland)]
    .filter(Boolean)
    .join(" · ");
  if (place) body.appendChild(el("p", null, place));

  const contact = el("p", "card-contact");
  if (center.email) contact.appendChild(el("span", null, center.email));
  else contact.appendChild(el("span", "no-email", "Keine E-Mail-Adresse – kann nicht ausgewählt werden"));
  if (center.telefon) contact.appendChild(el("span", null, center.telefon));
  body.appendChild(contact);

  // Nur echte Webadressen verlinken (kein javascript: o. Ä.).
  if (center.website && /^https?:\/\//i.test(center.website)) {
    const link = el("a", "card-link", center.website.replace(/^https?:\/\//i, ""));
    link.href = center.website;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    body.appendChild(link);
  }

  const offers = Object.entries(OFFERS).filter(([key]) => center[key]);
  if (offers.length) {
    const tags = el("div", "tag-list");
    for (const [, label] of offers) tags.appendChild(el("span", "tag", label));
    body.appendChild(tags);
  }
  card.appendChild(body);

  if (canEdit) {
    const edit = el("button", "text-button", "Bearbeiten");
    edit.type = "button";
    edit.addEventListener("click", () => openCenterForm(center));
    card.appendChild(edit);
  }
  return card;
}

/* ------------------------------------------------------------------ */
/* Auswahl                                                             */
/* ------------------------------------------------------------------ */

function toggleSelection(center, isSelected) {
  if (isSelected && center.email) {
    state.selected.set(center.id, { name: center.name, email: center.email });
  } else {
    state.selected.delete(center.id);
  }
  updateSelectionUi();
}

function updateSelectionUi() {
  const count = state.selected.size;
  $("selected-count").textContent = String(count);
  $("bulk-actions").hidden = count === 0;
  $("dashboard-recipient-count").textContent = String(count);
  $("email-recipient-count").textContent = String(count);
}

function selectVisible() {
  for (const center of state.items) {
    if (center.email) state.selected.set(center.id, { name: center.name, email: center.email });
  }
  renderResults();
  updateSelectionUi();
}

function clearSelection() {
  state.selected.clear();
  renderResults();
  updateSelectionUi();
}

/* ------------------------------------------------------------------ */
/* E-Mail-Zentrale                                                     */
/* ------------------------------------------------------------------ */

function selectedEmails() {
  const unique = new Set();
  for (const { email } of state.selected.values()) {
    // Mehrere Adressen in einem Feld (z. B. "a@x.de; b@y.de") aufteilen.
    for (const part of String(email).split(/[;,\s]+/)) {
      if (part.includes("@")) unique.add(part.trim());
    }
  }
  return [...unique];
}

function renderEmailRecipients() {
  $("email-recipients").value = selectedEmails().join(", ");
  $("email-recipient-count").textContent = String(state.selected.size);
}

function buildMailto(batch, subject, body) {
  const params = [`bcc=${encodeURIComponent(batch.join(","))}`];
  if (subject) params.push(`subject=${encodeURIComponent(subject)}`);
  if (body) params.push(`body=${encodeURIComponent(body)}`);
  return `mailto:?${params.join("&")}`;
}

function prepareEmail(event) {
  event.preventDefault();
  const message = $("email-form-message");
  const batchesBox = $("email-batches");
  batchesBox.replaceChildren();
  batchesBox.hidden = true;

  const emails = selectedEmails();
  const subject = $("email-subject").value.trim();
  const body = $("email-body").value.trim();

  if (!emails.length) {
    setMessage(message, "Bitte zuerst Einrichtungen mit E-Mail-Adresse auswählen.", "error");
    return;
  }
  if (!subject) {
    setMessage(message, "Bitte einen Betreff eingeben.", "error");
    $("email-subject").focus();
    return;
  }

  const batches = [];
  for (let i = 0; i < emails.length; i += MAIL_BATCH_SIZE) {
    batches.push(emails.slice(i, i + MAIL_BATCH_SIZE));
  }
  const links = batches.map((batch) => buildMailto(batch, subject, body));
  const tooLong = links.some((href) => href.length > MAILTO_WARN_LENGTH);

  if (links.length === 1 && !tooLong) {
    setMessage(message, `Dein Mailprogramm wird mit ${emails.length} Empfängern im BCC geöffnet.`, "success");
    window.location.href = links[0];
    return;
  }

  batchesBox.appendChild(
    el("p", null, `${emails.length} Empfänger, aufgeteilt in ${links.length} Nachrichten. Öffne die Teile nacheinander:`)
  );
  links.forEach((href, index) => {
    const link = el(
      "a",
      "secondary-button",
      `Teil ${index + 1} von ${links.length} öffnen (${batches[index].length} Empfänger)`
    );
    link.href = href;
    batchesBox.appendChild(link);
  });
  batchesBox.hidden = false;
  if (tooLong) {
    setMessage(
      message,
      "Hinweis: Die Nachricht ist sehr lang. Manche Mailprogramme kürzen lange Links – den Text ggf. im Mailprogramm einfügen.",
      "error"
    );
  } else {
    setMessage(message, "");
  }
}

function clearEmail() {
  $("email-subject").value = "";
  $("email-body").value = "";
  $("email-batches").replaceChildren();
  $("email-batches").hidden = true;
  setMessage($("email-form-message"), "");
}

/* ------------------------------------------------------------------ */
/* Datenpflege (nur editor/admin)                                      */
/* ------------------------------------------------------------------ */

function renderOfferCheckboxes() {
  const box = $("center-offers");
  for (const [key, label] of Object.entries(OFFERS)) {
    const wrapper = el("label", "offer-option");
    const input = el("input");
    input.type = "checkbox";
    input.value = label;
    input.dataset.key = key;
    wrapper.appendChild(input);
    wrapper.appendChild(el("span", null, label));
    box.appendChild(wrapper);
  }
}

function openCenterForm(center) {
  state.editing = center || null;
  $("center-form").reset();
  setMessage($("center-form-message"), "");

  const isEdit = Boolean(center);
  $("center-form-title").textContent = isEdit ? "Einrichtung bearbeiten" : "Einrichtung anlegen";
  $("center-edit-id").value = isEdit ? String(center.id) : "";
  $("center-id-field").hidden = isEdit;
  $("deactivate-center").hidden = !isEdit;
  $("etl-notice").hidden = !(isEdit && center.id < MANUAL_ID_START);

  if (isEdit) {
    $("center-name").value = center.name || "";
    $("center-email").value = center.email || "";
    $("center-phone").value = center.telefon || "";
    $("center-website").value = center.website || "";
    $("center-street").value = center.adresse || "";
    $("center-postcode").value = center.plz || "";
    $("center-city").value = center.ort || "";
    $("center-state").value = center.bundesland || "";
    document.querySelectorAll('#center-offers input[type="checkbox"]').forEach((input) => {
      input.checked = Boolean(center[input.dataset.key]);
    });
  }
  showView("datenpflege");
  (isEdit ? $("center-name") : $("center-id")).focus();
}

function extraServices(center) {
  // Leistungen außerhalb der sechs Standardangebote (z. B. aus dem Import)
  // beim Speichern erhalten, damit PUT sie nicht entfernt.
  if (!center || !center.leistungen) return [];
  const standard = new Set(Object.values(OFFERS));
  return center.leistungen
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s && !standard.has(s));
}

function collectPayload() {
  const services = [...document.querySelectorAll('#center-offers input[type="checkbox"]:checked')].map(
    (input) => input.value
  );
  return {
    name: $("center-name").value.trim(),
    email: $("center-email").value.trim(),
    telefon: $("center-phone").value.trim(),
    website: $("center-website").value.trim(),
    adresse: $("center-street").value.trim(),
    plz: $("center-postcode").value.trim(),
    ort: $("center-city").value.trim(),
    bundesland: $("center-state").value,
    services: [...services, ...extraServices(state.editing)],
    // Koordinaten werden im Formular nicht bearbeitet, aber beibehalten.
    latitude: state.editing ? state.editing.latitude : null,
    longitude: state.editing ? state.editing.longitude : null,
  };
}

function validatePayload(payload, isEdit) {
  if (!isEdit) {
    const id = Number($("center-id").value);
    if (!Number.isInteger(id) || id < MANUAL_ID_START) {
      return `Bitte eine ganzzahlige ID ab ${MANUAL_ID_START.toLocaleString("de-DE")} angeben.`;
    }
  }
  if (!payload.name) return "Bitte den Namen der Einrichtung angeben.";
  if (!/^\d{5}$/.test(payload.plz)) return "Die Postleitzahl muss aus genau 5 Ziffern bestehen.";
  if (!payload.ort) return "Bitte die Stadt oder Gemeinde angeben.";
  if (!payload.bundesland) return "Bitte ein Bundesland auswählen.";
  if (payload.website && !/^https?:\/\//i.test(payload.website)) {
    return "Die Internetseite muss mit http:// oder https:// beginnen.";
  }
  return null;
}

async function saveCenter(event) {
  event.preventDefault();
  const message = $("center-form-message");
  const isEdit = Boolean(state.editing);
  const payload = collectPayload();
  const problem = validatePayload(payload, isEdit);
  if (problem) {
    setMessage(message, problem, "error");
    return;
  }

  const button = $("save-center");
  button.disabled = true;
  try {
    if (isEdit) {
      await api(`/api/centers/${state.editing.id}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      payload.id = Number($("center-id").value);
      await api("/api/centers", { method: "POST", body: JSON.stringify(payload) });
    }
    setMessage(message, isEdit ? "Änderungen gespeichert." : "Einrichtung angelegt.", "success");
    await loadCenters();
    loadDashboardCount();
  } catch (error) {
    setMessage(message, error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function deactivateCenter() {
  const center = state.editing;
  if (!center) return;
  const ok = window.confirm(
    `„${center.name || "Einrichtung"}“ deaktivieren? Sie wird danach nicht mehr in der Liste angezeigt.`
  );
  if (!ok) return;
  try {
    await api(`/api/centers/${center.id}`, { method: "DELETE" });
    state.selected.delete(center.id);
    updateSelectionUi();
    state.editing = null;
    await loadCenters();
    loadDashboardCount();
    showView("einrichtungen");
    $("results-count").textContent = "Einrichtung deaktiviert.";
  } catch (error) {
    setMessage($("center-form-message"), error.message, "error");
  }
}

/* ------------------------------------------------------------------ */
/* Übersicht                                                           */
/* ------------------------------------------------------------------ */

async function loadDashboardCount() {
  try {
    const data = await api("/api/centers?limit=1");
    $("dashboard-center-count").textContent = data.total.toLocaleString("de-DE");
  } catch {
    $("dashboard-center-count").textContent = "–";
  }
}

/* ------------------------------------------------------------------ */
/* Start                                                               */
/* ------------------------------------------------------------------ */

function bindEvents() {
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      if (link.dataset.view === "datenpflege" && !state.editing) openCenterForm(null);
      else showView(link.dataset.view);
    });
  });
  document.querySelectorAll("[data-open-view]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.openView));
  });
  window.addEventListener("hashchange", () => showView(window.location.hash.slice(1)));

  $("search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    state.search = $("search-input").value.trim();
    state.angebot = $("offer-filter").value;
    state.bundesland = $("region-filter").value;
    state.offset = 0;
    loadCenters();
  });
  $("search-input").addEventListener(
    "input",
    debounce(() => {
      state.search = $("search-input").value.trim();
      state.offset = 0;
      loadCenters();
    }, 350)
  );
  for (const id of ["offer-filter", "region-filter"]) {
    $(id).addEventListener("change", () => {
      state.angebot = $("offer-filter").value;
      state.bundesland = $("region-filter").value;
      state.offset = 0;
      loadCenters();
    });
  }
  $("search-form").addEventListener("reset", () => {
    state.search = "";
    state.angebot = "";
    state.bundesland = "";
    state.offset = 0;
    loadCenters();
  });

  $("previous-page").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - PAGE_SIZE);
    loadCenters();
  });
  $("next-page").addEventListener("click", () => {
    state.offset += PAGE_SIZE;
    loadCenters();
  });

  $("select-visible").addEventListener("click", selectVisible);
  $("clear-selection").addEventListener("click", clearSelection);

  $("email-form").addEventListener("submit", prepareEmail);
  $("clear-email").addEventListener("click", clearEmail);

  if (canEdit) {
    renderOfferCheckboxes();
    $("center-form").addEventListener("submit", saveCenter);
    $("deactivate-center").addEventListener("click", deactivateCenter);
    $("new-center").addEventListener("click", () => openCenterForm(null));
    $("quick-new-center").addEventListener("click", () => openCenterForm(null));
  }
}

bindEvents();
const initialView = window.location.hash.slice(1) || "einrichtungen";
if (initialView === "datenpflege" && canEdit) openCenterForm(null);
else showView(initialView);
loadBundeslaender();
loadCenters();
loadDashboardCount();
updateSelectionUi();
