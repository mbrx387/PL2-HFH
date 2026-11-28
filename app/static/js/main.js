/**
 * Pflegezentren-Finder – Oberfläche (ohne Build-Schritt, ohne Framework).
 *
 * Ansichten: Übersicht, Einrichtungen, Datenpflege (nur editor/admin),
 * E-Mail-Zentrale, Versandhistorie, Benutzerverwaltung. Die Rechte prüft der Server
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
  benutzer: { title: "Benutzerverwaltung", desc: "Benutzerkonten verwalten." },
};

/*getrennte Frontend-Berechtigung für Benutzerverwaltung*/
const canEdit =
  document.body.dataset.canEdit === "true";
const canManageUsers =
  document.body.dataset.canManageUsers === "true";
// Token fuer schreibende Admin-API-Aufrufe
const adminCsrf = document.body.dataset.adminCsrf || "";
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
  if (!VIEWS[name] || (name === "datenpflege" && !canEdit) || (name === "benutzer" && !canManageUsers)) {
    name = "einrichtungen";
  }

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
// Beim Öffnen der Historie oder des Dashboards die dokumentierten E-Mail-Übergaben aus PR#47 laden.
  if (name === "historie" || name === "dashboard") loadMailHistory();

// Benutzerdaten nur bei Admin-Berechtigung laden
 if (name === "benutzer" && canManageUsers) loadUsers();
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

// GEÄNDERT AP6:
// Die vorhandene E-Mail-Vorbereitung wird mit PR#47 verbunden. Ausgewählte Einrichtungs-IDs oder gesetzte Filter werden an das Backend gesendet. AP5 erstellt die BCC-Gruppen.
async function prepareEmail(event) {
  event.preventDefault();

  const message = $("email-form-message");
  const box = $("email-batches");

  box.replaceChildren();
  box.hidden = true;

  const subject = $("email-subject").value.trim();
  if (!subject) {
    setMessage(message, "Bitte einen Betreff eingeben.", "error");
    return;
  }

  // IDs der manuell ausgewählten Einrichtungen sammeln.
  const ids = [...state.selected.keys()];

  // Alternativ die aktuellen Suchfilter verwenden.
  const filters = {
    search: state.search || null,
    bundesland: state.bundesland || null,
    angebot: state.angebot || null,
  };

  if (!ids.length && !Object.values(filters).some(Boolean)) {
    setMessage(message, "Bitte Einrichtungen auswählen oder Filter setzen.", "error");
    return;
  }

  try {
    // Anfrage für den AP5-Endpunkt vorbereiten.
    const request = {
      subject,
      body: $("email-body").value.trim(),
    };

    // Manuelle Auswahl hat Vorrang vor Filtern.
    if (ids.length) {
      request.center_ids = ids;
    } else {
      request.filters = filters;
    }

    // AP5 übernimmt die Empfängerauswahl und BCC-Aufteilung.
    const result = await api("/api/mail/prepare", {
      method: "POST",
      body: JSON.stringify(request),
    });

    setMessage(
      message,
      `${result.recipient_count} Empfänger in ${result.batch_count} BCC-Gruppen vorbereitet.`,
      "success"
    );

    // Für jede vorbereitete BCC-Gruppe einen Button erstellen.
    for (const batch of result.batches) {
      const button = el(
        "button",
        "secondary-button",
        `Teil ${batch.number} öffnen (${batch.recipient_count} Empfänger)`
      );

      button.type = "button";

      button.addEventListener("click", async () => {
        button.disabled = true;

        try {
          // Übergabe an das Mailprogramm dokumentieren.
          const handoff = await api("/api/mail/handoff", {
            method: "POST",
            body: JSON.stringify({
              handoff_token: batch.handoff_token,
            }),
          });

          // Nur mailto-Links zulassen.
          if (!handoff.mailto_url?.startsWith("mailto:")) {
            throw new Error("Ungültiger Mail-Link.");
          }

          // Lokales Mailprogramm öffnen.
          window.location.href = handoff.mailto_url;

          // WICHTIG: Die Historie dokumentiert nur die Übergabe, nicht den tatsächlichen Versand.
          setMessage(
            message,
            "Übergabe protokolliert. Nach dem Senden bitte in der Versandhistorie als versendet markieren.",
            "success"
          );

        } catch (error) {
          setMessage(message, error.message, "error");

        } finally {
          button.disabled = false;
        }
      });

      box.appendChild(button);
    }

    box.hidden = result.batches.length === 0;

  } catch (error) {
    setMessage(
      message,
      `Vorbereitung fehlgeschlagen: ${error.message}`,
      "error"
    );
  }
}

function clearEmail() {
  $("email-subject").value = "";
  $("email-body").value = "";

  $("email-batches").replaceChildren();
  $("email-batches").hidden = true;

  setMessage($("email-form-message"), "");
}

// NEU AP5: Versandhistorie mit Filtern (Zeit, Region, Versand, Text), Details,
// Versandbestätigung und "Weitere Einträge laden".
const HISTORY_PAGE_SIZE = 50;
const historyState = { loaded: 0, last: null, ticket: 0 };

const DELIVERY_LABELS = {
  sent: ["Versendet", "is-online"],
  not_sent: ["Nicht versendet", "is-offline"],
};

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString("de-DE") : "";
}

function initHistoryFilters() {
  const years = $("history-year");
  const regions = $("history-region");
  if (!years || !regions) return;
  // Die Historie gibt es seit 2026; neuere Jahre kommen automatisch dazu.
  for (let year = new Date().getFullYear(); year >= 2026; year--) {
    const opt = el("option", null, String(year));
    opt.value = String(year);
    years.appendChild(opt);
  }
  const sorted = Object.entries(LAENDER).sort((a, b) => a[1].localeCompare(b[1], "de"));
  for (const [code, name] of sorted) {
    const opt = el("option", null, name);
    opt.value = code;
    regions.appendChild(opt);
  }
}

// Baut die Abfrage für GET /api/mail-history aus den Filterfeldern.
function historyQuery(extra = {}) {
  const params = new URLSearchParams();
  const year = $("history-year")?.value || "";
  const period = $("history-period")?.value || "";
  if (year) {
    params.set("year", year);
    if (period.startsWith("q")) params.set("quarter", period.slice(1));
    if (period.startsWith("m")) params.set("month", period.slice(1));
  }
  const region = $("history-region")?.value || "";
  if (region) params.set("bundesland", region);
  const delivery = $("history-delivery-filter")?.value || "";
  if (delivery) params.set("delivery", delivery);
  const search = ($("history-search")?.value || "").trim();
  if (search) params.set("search", search);
  const filtered = [...params.keys()].length > 0;
  for (const [key, value] of Object.entries(extra)) params.set(key, String(value));
  return { params, filtered };
}

function deliveryCell(item) {
  const cell = el("td");
  const [label, cls] = DELIVERY_LABELS[item.delivery_status] || ["Übergeben – Versand offen", ""];
  const pill = el("span", `status-pill ${cls}`.trim(), label);
  pill.title = item.delivery_confirmed_by
    ? `markiert von ${item.delivery_confirmed_by}`
    : "An das Mailprogramm übergeben";
  cell.appendChild(pill);
  if (item.batch_count > 1) {
    cell.appendChild(el("span", "history-batch", `Teil ${item.batch_number}/${item.batch_count}`));
  }
  return cell;
}

function deliveryText(item) {
  if (!item.delivery_status) return "Noch nicht bestätigt";
  const who = item.delivery_confirmed_by ? ` von ${item.delivery_confirmed_by}` : "";
  return `${DELIVERY_LABELS[item.delivery_status][0]} – markiert am ${formatDateTime(item.delivery_confirmed_at)}${who}`;
}

// Detailzeile: dokumentiert Nachricht, Empfänger, Region, Person und Versand.
function historyDetailRow(item) {
  const row = el("tr", "history-detail");
  row.id = `history-detail-${item.id}`;
  row.hidden = true;
  const cell = el("td");
  cell.colSpan = 5;
  const list = el("dl", "history-detail-list");
  const add = (label, value, className) => {
    list.appendChild(el("dt", null, label));
    list.appendChild(el("dd", className, value));
  };
  add("Nachricht", item.body || "(kein Text)", "history-message-text");
  add(`Empfänger im BCC (${item.recipient_count})`, item.recipients.join(", "), "history-recipients");
  add("Bundesländer", item.bundeslaender.map(landName).join(", ") || "–");
  add("Teil", `${item.batch_number} von ${item.batch_count}`);
  add("Übergeben von", item.created_by || "– (ohne Anmeldung)");
  add("Versand", deliveryText(item));
  cell.appendChild(list);
  row.appendChild(cell);
  return row;
}

function deliveryActions(item, rows) {
  const cell = el("td", "history-actions");
  const choices = item.delivery_status
    ? [[null, "Zurücksetzen"]]
    : [["sent", "Versendet"], ["not_sent", "Nicht versendet"]];
  for (const [value, label] of choices) {
    const button = el("button", "secondary-button", label);
    button.type = "button";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const updated = await api(`/api/mail-history/${item.id}/delivery`, {
          method: "PUT",
          body: JSON.stringify({ delivery_status: value }),
        });
        if ($("history-delivery-filter")?.value) {
          // Mit Versand-Filter passt der Eintrag evtl. nicht mehr: Liste neu laden.
          await loadMailHistory();
          return;
        }
        // Sonst nur diesen Eintrag austauschen (geöffnete Details bleiben offen).
        const wasOpen = !rows.detail.hidden;
        const fresh = historyRows(updated);
        rows.row.replaceWith(fresh.row);
        rows.detail.replaceWith(fresh.detail);
        if (wasOpen) fresh.toggle.click();
        await updateHistorySummary();
      } catch (error) {
        setMessage($("mail-history-message"), error.message, "error");
        button.disabled = false;
      }
    });
    cell.appendChild(button);
  }
  return cell;
}

function historyRows(item) {
  const row = el("tr");
  row.appendChild(el("td", null, formatDateTime(item.created_at)));

  const subject = el("td");
  subject.appendChild(el("span", "history-subject", item.subject));
  if (item.bundeslaender.length) {
    subject.appendChild(el("span", "history-meta", item.bundeslaender.map(landName).join(", ")));
  }
  const toggle = el("button", "history-toggle", "Details anzeigen");
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", "false");
  subject.appendChild(toggle);
  row.appendChild(subject);

  row.appendChild(el("td", null, String(item.recipient_count)));
  row.appendChild(deliveryCell(item));

  const detail = historyDetailRow(item);
  toggle.setAttribute("aria-controls", detail.id);
  toggle.addEventListener("click", () => {
    const open = detail.hidden;
    detail.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "Details ausblenden" : "Details anzeigen";
  });

  const rows = { row, detail, toggle };
  row.appendChild(deliveryActions(item, rows));
  return rows;
}

// Zusammenfassung über der Tabelle und Zahl im Dashboard (immer ohne Filter).
async function updateHistorySummary() {
  const last = historyState.last;
  const all = await api("/api/mail-history?limit=1");
  const open = await api("/api/mail-history?limit=1&delivery=open");
  $("dashboard-history-count").textContent = String(all.total);
  if (!last) return;
  const scope = last.filtered ? "im Filter" : "insgesamt";
  const entries = `${last.total} ${last.total === 1 ? "Übergabe" : "Übergaben"}`;
  const people = `${last.recipientTotal} ${last.recipientTotal === 1 ? "Empfänger" : "Empfängern"}`;
  setMessage(
    $("mail-history-message"),
    `${entries} ${scope} mit zusammen ${people}, ${historyState.loaded} angezeigt. ` +
      `Noch nicht als versendet bestätigt: ${open.total}.`
  );
}

// Die Versandhistorie (Backend aus PR#47) in der Tabelle und im Dashboard anzeigen.
async function loadMailHistory(append = false) {
  const tbody = $("mail-history-body");
  const message = $("mail-history-message");
  const more = $("history-more");

  if (!tbody || !message) return;

  // Nur die zuletzt gestartete Abfrage darf die Tabelle füllen (schnelle Filterwechsel).
  const ticket = ++historyState.ticket;
  setMessage(message, "Historie wird geladen ...");
  if (more) more.disabled = true;

  try {
    const offset = append ? historyState.loaded : 0;
    const { params, filtered } = historyQuery({ limit: HISTORY_PAGE_SIZE, offset });
    const data = await api(`/api/mail-history?${params}`);
    if (ticket !== historyState.ticket) return;
    if (!append) {
      tbody.replaceChildren();
      historyState.loaded = 0;
    }

    for (const item of data.items) {
      const rows = historyRows(item);
      tbody.append(rows.row, rows.detail);
    }
    historyState.loaded += data.items.length;
    historyState.last = { total: data.total, recipientTotal: data.recipient_total, filtered };

    // Hinweis bei leerer Historie anzeigen.
    if (!historyState.loaded) {
      const row = el("tr");
      const cell = el(
        "td",
        "empty-cell",
        filtered ? "Keine Einträge für diesen Filter." : "Noch keine Übergaben dokumentiert."
      );
      cell.colSpan = 5;
      row.appendChild(cell);
      tbody.appendChild(row);
    }

    if (more) {
      more.hidden = historyState.loaded >= data.total;
      more.disabled = false;
    }
    await updateHistorySummary();
  } catch (error) {
    if (ticket !== historyState.ticket) return;
    $("dashboard-history-count").textContent = "–";
    if (more) more.disabled = false;

    setMessage(
      message,
      `Historie konnte nicht geladen werden: ${error.message}`,
      "error"
    );
  }
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
  $("center-name").focus();
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

function validatePayload(payload) {
  // Die ID vergibt der Server (ab MANUAL_ID_START) — es gibt kein ID-Feld mehr.
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
  const problem = validatePayload(payload);
  if (problem) {
    setMessage(message, problem, "error");
    return;
  }

  const button = $("save-center");
  button.disabled = true;
  try {
    if (isEdit) {
      await api(`/api/centers/${state.editing.id}`, { method: "PUT", body: JSON.stringify(payload) });
      setMessage(message, "Änderungen gespeichert.", "success");
    } else {
      const created = await api("/api/centers", { method: "POST", body: JSON.stringify(payload) });
      setMessage(message, `Einrichtung angelegt (ID ${created.id.toLocaleString("de-DE")}).`, "success");
    }
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
/* Benutzerverwaltung – nur Frontend, kein Keycloak-Code              */
/* ------------------------------------------------------------------ */
function filterUsers() {
  const searchInput = $("users-search");
  const table = $("users-table-body");
  if (!searchInput || !table) return;

  const query = searchInput.value.trim().toLocaleLowerCase("de-DE");
  for (const row of table.querySelectorAll("tr")) {
    const username = (row.cells[0]?.textContent || "").toLocaleLowerCase("de-DE");
    const email = (row.cells[1]?.textContent || "").toLocaleLowerCase("de-DE");
    row.hidden = !username.includes(query) && !email.includes(query);
  }
}
// Benutzer aus der vorhandenen FastAPI-Schnittstelle laden.
async function loadUsers() {
  const table = $("users-table-body");
  const message = $("users-list-message");
  if (!table || !message) return;

  table.replaceChildren();
  setMessage(message, "Benutzer werden geladen …");

  try {
    const users = await api("/api/admin/users");
    if (!Array.isArray(users)) throw new Error("Ungültige Antwort der Benutzer-API.");

    for (const user of users) {
      const row = el("tr");
      row.appendChild(el("td", null, user.username || "–"));
      row.appendChild(el("td", null, user.email || "–"));
      row.appendChild(el("td", null, user.enabled ? "Aktiv" : "Deaktiviert"));

      const actions = el("td");
      const button = el("button", "secondary-button", user.enabled ? "Deaktivieren" : "Aktivieren");
      button.type = "button";
      button.disabled = Boolean(user.is_self);
      if (user.is_self) button.title = "Eigenes Konto kann nicht deaktiviert werden";

      button.addEventListener("click", async () => {
        if (!confirm(`Benutzer „${user.username}“ ${user.enabled ? "deaktivieren" : "aktivieren"}?`)) return;
        button.disabled = true;
        try {
          await api(`/api/admin/users/${encodeURIComponent(user.id)}/enabled`, {
            method: "PUT",
            // CSRF-Schutz
            headers: { "Content-Type": "application/json", "X-CSRF-Token": adminCsrf },
            body: JSON.stringify({ enabled: !user.enabled }),
          });
          await loadUsers();
        } catch (error) {
          setMessage(message, error.message, "error");
          button.disabled = false;
        }
      });

    //  Gruppenwechsel in der Benutzerliste
    const groupSelect = el("select");
   const noGroup = el("option", null, "Keine Gruppe");
    noGroup.value = "";
    groupSelect.appendChild(noGroup);
    for (const group of ["Lesend", "Redaktion", "Admins"]) {
      const option = el("option", null, group);
        option.value = group;
           groupSelect.appendChild(option);
         }
        groupSelect.value = user.group || "";
        groupSelect.disabled = Boolean(user.is_self) || user.group === "Admins";
  
       const saveGroupButton = el("button", "secondary-button", "Gruppe speichern");
      saveGroupButton.type = "button";
       saveGroupButton.disabled = groupSelect.disabled;
       saveGroupButton.addEventListener("click", async () => {
       const selectedGroup = groupSelect.value || null;
       if (selectedGroup === user.group) return;
        if (!confirm(`Gruppe für „${user.username}“ ändern?`)) return;
        saveGroupButton.disabled = true;
         try {
           await api(`/api/admin/users/${encodeURIComponent(user.id)}/group`, {
            method: "PUT",
             headers: { "Content-Type": "application/json", "X-CSRF-Token": adminCsrf },
              body: JSON.stringify({ group: selectedGroup }),
           });
             await loadUsers();
           } catch (error) {
             setMessage(message, `Gruppe konnte nicht geändert werden: ${error.message}`, "error");
            saveGroupButton.disabled = false;
           }
        });
         actions.appendChild(groupSelect);
       actions.appendChild(saveGroupButton);
        for (const [endpoint, label] of [["logout", "Sitzungen beenden"], ["reset-otp", "OTP zurücksetzen"]]) {
        const action = el("button", "secondary-button", label);
        action.type = "button";
        action.addEventListener("click", async () => {
          if (!confirm(`${label}: ${user.username}?`)) return;
          action.disabled = true;
          try {
            await api(`/api/admin/users/${encodeURIComponent(user.id)}/${endpoint}`, {
              method: "POST", headers: {"X-CSRF-Token": adminCsrf},
            });
            setMessage(message, "Aktion in Keycloak ausgeführt.", "success");
          } catch (error) { setMessage(message, error.message, "error"); }
          finally { action.disabled = false; }
        });
        actions.appendChild(action);
      }
    
      actions.appendChild(button);
      row.appendChild(actions);
      table.appendChild(row);
    }
     // Aktuellen Suchfilter nach dem Neuladen erneut anwenden.
    filterUsers();
    
    setMessage(message, users.length ? `${users.length} Benutzer angezeigt.` : "Noch keine Benutzer vorhanden.");
  } catch (error) {
    setMessage(message, `Benutzer konnten nicht geladen werden: ${error.message}`, "error");
  }
}

// Formular sendet Daten an FastAPI; Keycloak wird nicht im Browser angesprochen.
async function createUser(event) {
  event.preventDefault();
  const form = $("user-create-form");
  const message = $("user-message");
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;

  try {
    await api("/api/admin/users", {
      method: "POST",
      // CSRF-Schutz
      headers: { "Content-Type": "application/json", "X-CSRF-Token": adminCsrf },
      body: JSON.stringify({
        username: $("user-username").value.trim(),
        email: $("user-email").value.trim(),
        password: $("user-password").value,
        group: $("user-group").value,
      }),
    });
    form.reset();
    setMessage(message, "Benutzer erfolgreich angelegt.", "success");
    await loadUsers();
  } catch (error) {
    setMessage(message, `Benutzer konnte nicht angelegt werden: ${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
}

/* ------------------------------------------------------------------ */
/* Start                                                               */
/* ------------------------------------------------------------------ */

function bindEvents() {
 // Admin-Funktionen nur binden, wenn der Bereich vorhanden ist.
  if (canManageUsers) {
    const userForm = $("user-create-form");
    const usersRefresh = $("users-refresh");
    if (userForm) userForm.addEventListener("submit", createUser);
    if (usersRefresh) usersRefresh.addEventListener("click", loadUsers);
  
// Live-Suche in der Benutzerverwaltung aktivieren.
 const usersSearch = $("users-search");
    if (usersSearch) {
      usersSearch.addEventListener("input", filterUsers);
    }
  }
  
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

  // Das E-Mail-Formular nutzt die AP5-Backend-Anbindung.
  $("email-form").addEventListener("submit", prepareEmail);
  // NEU AP5: Filter der Versandhistorie (Zeit, Region, Versand, Text) und "Weitere laden".
  const historyForm = $("history-filter-form");
  if (historyForm) {
    initHistoryFilters();
    historyForm.addEventListener("submit", (event) => {
      event.preventDefault();
      loadMailHistory();
    });
    $("history-year").addEventListener("change", () => {
      const period = $("history-period");
      period.disabled = !$("history-year").value;
      if (period.disabled) period.value = "";
      loadMailHistory();
    });
    for (const id of ["history-period", "history-region", "history-delivery-filter"]) {
      $(id).addEventListener("change", () => loadMailHistory());
    }
    $("history-reset").addEventListener("click", () => {
      historyForm.reset();
      $("history-period").disabled = true;
      loadMailHistory();
    });
    $("history-more").addEventListener("click", () => loadMailHistory(true));
  }
  // Zurücksetzen-Funktion inklusive BCC-Gruppen verwenden.
  $("clear-email").addEventListener("click", clearEmail);

  if (canEdit) {
    renderOfferCheckboxes();
    $("center-form").addEventListener("submit", saveCenter);
    $("deactivate-center").addEventListener("click", deactivateCenter);
    $("new-center").addEventListener("click", () => openCenterForm(null));
    const quickNew = $("quick-new-center");
    if (quickNew) quickNew.addEventListener("click", () => openCenterForm(null));
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
