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
const DEFAULT_MAIL_SUBJECT = "Anfrage Pflege-/Beratungsstelle";

const state = {
  search: "",
  bundesland: "",
  angebot: "",
  // Auswahl bleibt ueber Filteraenderungen hinweg erhalten (Map: id -> {name, email}).
  selected: new Map(),
  // AP5: vorbereitete BCC-Gruppen, die noch per Klick geoeffnet werden muessen.
  pendingMail: null,
  mailBusy: false,
};

const els = {
  search: document.getElementById("search"),
  bundeslandFilter: document.getElementById("bundesland-filter"),
  angebotFilter: document.getElementById("angebot-filter"),
  list: document.getElementById("center-list"),
  resultCount: document.getElementById("result-count"),
  selectedCount: document.getElementById("selected-count"),
  sendMail: document.getElementById("send-mail"),
  mailFiltered: document.getElementById("mail-filtered"),
  mailStatus: document.getElementById("mail-status"),
  mailSubject: document.getElementById("email-subject"),
  mailBody: document.getElementById("email-body"),
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
  resetPendingMail("ids");
  updateSelectedUi();
}

function updateSelectedUi() {
  els.selectedCount.textContent = String(state.selected.size);
  const pending = state.pendingMail;
  els.sendMail.disabled = state.mailBusy || (!pending && state.selected.size === 0);
  els.sendMail.textContent = pending
    ? `Nächste BCC-E-Mail öffnen (${pending.index + 1}/${pending.batches.length})`
    : "E-Mail an Auswahl senden (öffnet Ihr Mailprogramm)";
  if (els.mailFiltered) els.mailFiltered.disabled = state.mailBusy || !hasActiveFilter();
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
  resetPendingMail();
  updateSelectedUi();
}

/* ---------------------------------------------------------------------------
 * AP5: E-Mail-Uebergabe an das lokale Mailprogramm
 *
 * Der Browser schickt nur Einrichtungs-IDs oder Filter an den Server. Der
 * Server holt die Adressen aus der Datenbank, teilt sie in BCC-Gruppen
 * (max. 20 Empfaenger, begrenzte mailto:-Laenge) und protokolliert jede
 * geoeffnete Gruppe in der Historie. Jede Gruppe oeffnet sich nur durch einen
 * eigenen Klick. Bewusst kein alert()/confirm(): Dialoge verbrauchen die
 * "Nutzer-Geste", die Browser zum Oeffnen des Mailprogramms verlangen.
 *
 * Wichtig: mailto: kann NICHT bestaetigen, dass die Mail wirklich abgeschickt
 * wurde. Die Historie dokumentiert nur die Uebergabe an das Mailprogramm.
 * ------------------------------------------------------------------------- */

function hasActiveFilter() {
  return Boolean(state.search || state.bundesland || state.angebot);
}

function setMailStatus(text) {
  if (els.mailStatus) els.mailStatus.textContent = text;
}

function resetPendingMail(mode) {
  // mode "ids": nur Checkbox-Vorbereitung verwerfen, "filter": nur Filter-Vorbereitung,
  // ohne mode: jede Vorbereitung verwerfen (z.B. "Auswahl leeren").
  if (state.pendingMail && (!mode || state.pendingMail.mode === mode)) {
    state.pendingMail = null;
    setMailStatus("");
  }
}

function getMailContent() {
  const subject = els.mailSubject ? els.mailSubject.value.trim() : "";
  const body = els.mailBody ? els.mailBody.value : "";
  return { subject: subject || DEFAULT_MAIL_SUBJECT, body };
}

function errorText(data, status) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length && detail[0].msg) return detail[0].msg;
  return `Fehler (HTTP ${status})`;
}

async function postJson(url, payload) {
  // redirect "manual": Ist die Anmeldung abgelaufen, leitet die App auf /auth/login
  // um. Das soll als verstaendlicher Hinweis ankommen statt als unklarer Fehler.
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    redirect: "manual",
  });
  if (res.type === "opaqueredirect" || res.status === 401) {
    throw new Error("Anmeldung abgelaufen – bitte Seite neu laden und erneut anmelden.");
  }
  let data = null;
  try {
    data = await res.json();
  } catch (_error) {
    data = null;
  }
  if (!res.ok) {
    const error = new Error(errorText(data, res.status));
    error.status = res.status;
    throw error;
  }
  return data;
}

function describePrepared(result) {
  const parts = [`${result.recipient_count} Empfänger in ${result.batch_count} BCC-E-Mail(s)`];
  const skipped = result.centers_without_email + result.centers_without_valid_email;
  if (skipped > 0) parts.push(`${skipped} Einrichtung(en) ohne E-Mail-Adresse übersprungen`);
  if (result.duplicate_emails > 0) parts.push(`${result.duplicate_emails} doppelte Adresse(n) entfernt`);
  return parts.join(" · ");
}

async function prepareMail(selection, mode) {
  const result = await postJson("/api/mail/prepare", { ...selection, ...getMailContent() });
  state.pendingMail = { mode, batches: result.batches, index: 0, summary: describePrepared(result) };
  setMailStatus(state.pendingMail.summary);
}

async function openNextBatch() {
  const pending = state.pendingMail;
  const batch = pending.batches[pending.index];
  let data;
  try {
    data = await postJson("/api/mail/handoff", { handoff_token: batch.handoff_token });
  } catch (error) {
    if (error.status === 422) state.pendingMail = null; // Vorbereitung abgelaufen: neu starten
    throw error;
  }
  pending.index += 1;
  if (pending.index >= pending.batches.length) {
    state.pendingMail = null;
    setMailStatus(
      `Alle ${pending.batches.length} BCC-E-Mail(s) an das Mailprogramm übergeben – dort prüfen und absenden.`
    );
  } else {
    setMailStatus(`BCC-E-Mail ${pending.index}/${pending.batches.length} übergeben. ${pending.summary}`);
  }
  // Oeffnet das Mailprogramm. Ob die Mail dort abgeschickt wird, ist nicht feststellbar.
  window.location.href = data.mailto_url;
}

async function runMailAction(action) {
  if (state.mailBusy) return;
  state.mailBusy = true;
  updateSelectedUi();
  try {
    await action();
  } catch (error) {
    setMailStatus(`E-Mail-Übergabe nicht möglich: ${error.message}`);
  } finally {
    state.mailBusy = false;
    updateSelectedUi();
  }
}

function sendMail() {
  // Checkbox-Auswahl: erster Klick bereitet vor und oeffnet sofort die erste
  // BCC-E-Mail; jeder weitere Klick oeffnet die naechste Gruppe.
  return runMailAction(async () => {
    if (!state.pendingMail) {
      const centerIds = [...state.selected.keys()];
      if (centerIds.length === 0) return;
      await prepareMail({ center_ids: centerIds }, "ids");
    }
    await openNextBatch();
  });
}

function sendFilteredMail() {
  // Filter-Auswahl kann viel mehr Einrichtungen umfassen als die 200 angezeigten.
  // Deshalb zuerst NUR vorbereiten und die Anzahl zeigen; geoeffnet wird erst
  // mit dem naechsten Klick auf "Nächste BCC-E-Mail öffnen".
  return runMailAction(async () => {
    if (!hasActiveFilter()) return;
    state.pendingMail = null;
    const filters = {
      search: state.search || null,
      bundesland: state.bundesland || null,
      angebot: state.angebot || null,
    };
    await prepareMail({ filters }, "filter");
    setMailStatus(`${state.pendingMail.summary}. Zum Öffnen unten auf „Nächste BCC-E-Mail öffnen“ klicken.`);
  });
}

function onFilterChanged() {
  resetPendingMail("filter");
  updateSelectedUi();
  loadCenters();
}

els.search.addEventListener(
  "input",
  debounce((e) => {
    state.search = e.target.value.trim();
    onFilterChanged();
  }, 300)
);
els.bundeslandFilter.addEventListener("change", (e) => {
  state.bundesland = e.target.value;
  onFilterChanged();
});
els.angebotFilter.addEventListener("change", (e) => {
  state.angebot = e.target.value;
  onFilterChanged();
});
els.selectAll.addEventListener("click", selectAllVisible);
els.selectNone.addEventListener("click", clearSelection);
els.sendMail.addEventListener("click", sendMail);
if (els.mailFiltered) els.mailFiltered.addEventListener("click", sendFilteredMail);

loadBundeslaender();
loadCenters();
