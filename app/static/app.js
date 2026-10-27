/* FF Etichette — frontend senza build. */
"use strict";

const TAGLIE = ["XS", "S", "M", "L", "XL", "XXL", "3XL"];
const BOZZA_KEY = "ff-etichette-bozza";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

let stato = caricaBozza() || nuovaCommessa();
let sel = { a: 0, r: 0 };           // riga selezionata per l'anteprima
let impostazioni = {};

function nuovaCommessa() {
  return { nome: "", articoli: [{ descrizione: "", righe: [{ taglia: "M", copie: 1 }] }] };
}

// ------------------------------------------------------------------ API
async function api(path, opts = {}) {
  const o = { ...opts, headers: { ...(opts.headers || {}) } };
  if (o.json !== undefined) {
    o.body = JSON.stringify(o.json); delete o.json;
    o.headers["Content-Type"] = "application/json";
    o.method = o.method || "POST";
  }
  const res = await fetch(path, o);
  if (res.status === 401 && path !== "/api/accesso") {
    await chiediPin();
    return api(path, opts);
  }
  if (!res.ok) {
    let msg = `Errore ${res.status}`;
    try { const j = await res.json(); if (j.detail) msg = typeof j.detail === "string" ? j.detail : msg; } catch (_) {}
    const err = new Error(msg); err.status = res.status; throw err;
  }
  return res;
}

function commessaPulita() {
  return {
    nome: stato.nome.trim(),
    articoli: stato.articoli.map(a => ({
      descrizione: a.descrizione.trim(),
      righe: a.righe.filter(r => r.taglia.trim() && r.copie > 0)
                    .map(r => ({ taglia: r.taglia.trim(), copie: r.copie })),
    })).filter(a => a.righe.length),
  };
}

// ------------------------------------------------------------------ bozza (solo comodità locale)
function salvaBozza() {
  try { localStorage.setItem(BOZZA_KEY, JSON.stringify(stato)); } catch (_) {}
}
function caricaBozza() {
  try {
    const s = JSON.parse(localStorage.getItem(BOZZA_KEY));
    if (s && Array.isArray(s.articoli)) return s;
  } catch (_) {}
  return null;
}

// ------------------------------------------------------------------ rendering form
function render() {
  $("#commessa").value = stato.nome;
  const box = $("#articoli");
  box.textContent = "";
  stato.articoli.forEach((art, ai) => {
    const card = $("#tpl-articolo").content.firstElementChild.cloneNode(true);
    card.dataset.a = ai;
    $(".articolo-n", card).textContent = `Articolo ${ai + 1}`;
    const d = $(".descrizione", card);
    d.value = art.descrizione;
    d.addEventListener("input", () => { art.descrizione = d.value; selezione(ai, sel.a === ai ? sel.r : 0); cambiato(); });
    d.addEventListener("focus", () => selezione(ai, sel.a === ai ? sel.r : 0));
    $(".rm-articolo", card).addEventListener("click", () => {
      if (stato.articoli.length === 1) { stato.articoli = nuovaCommessa().articoli; }
      else if (!confirmaRimozione(art)) return;
      else stato.articoli.splice(ai, 1);
      sel = { a: Math.min(sel.a, stato.articoli.length - 1), r: 0 };
      render(); cambiato();
    });
    const righe = $(".righe", card);
    art.righe.forEach((r, ri) => righe.appendChild(rigaEl(art, ai, r, ri)));
    $(".add-taglia", card).addEventListener("click", () => {
      art.righe.push({ taglia: prossimaTaglia(art), copie: 1 });
      sel = { a: ai, r: art.righe.length - 1 };
      render(); cambiato();
      const sels = $$(`.articolo[data-a="${ai}"] .riga .copie`); sels[sels.length - 1]?.focus();
    });
    box.appendChild(card);
  });
  aggiornaTotali();
  evidenzia();
}

function confirmaRimozione(art) {
  const n = art.righe.reduce((s, r) => s + r.copie, 0);
  return n === 0 && !art.descrizione ? true : confirm(`Eliminare l'articolo "${art.descrizione || "senza nome"}"?`);
}

function prossimaTaglia(art) {
  const usate = new Set(art.righe.map(r => r.taglia.toUpperCase()));
  const last = art.righe.length ? TAGLIE.indexOf(art.righe[art.righe.length - 1].taglia.toUpperCase()) : -1;
  for (let k = 1; k <= TAGLIE.length; k++) {
    const t = TAGLIE[(Math.max(last, -1) + k + TAGLIE.length) % TAGLIE.length];
    if (!usate.has(t)) return t;
  }
  return "M";
}

function rigaEl(art, ai, r, ri) {
  const el = $("#tpl-riga").content.firstElementChild.cloneNode(true);
  el.dataset.a = ai; el.dataset.r = ri;
  const s = $(".taglia", el), altra = $(".taglia-altra", el), copie = $(".copie", el);
  const std = TAGLIE.includes(r.taglia.toUpperCase());
  s.value = std ? r.taglia.toUpperCase() : "__altra";
  altra.hidden = std; altra.value = std ? "" : r.taglia;
  copie.value = r.copie;

  const focusSel = () => selezione(ai, ri);
  el.addEventListener("pointerdown", focusSel);
  el.addEventListener("focusin", focusSel);
  s.addEventListener("change", () => {
    if (s.value === "__altra") { altra.hidden = false; r.taglia = altra.value.trim() || ""; altra.focus(); }
    else { altra.hidden = true; r.taglia = s.value; }
    cambiato();
  });
  altra.addEventListener("input", () => { r.taglia = altra.value; cambiato(); });
  const set = v => {
    const n = Math.max(0, Math.min(9999, Number.isFinite(v) ? Math.round(v) : 0));
    r.copie = n; copie.value = n; cambiato();
  };
  $(".meno", el).addEventListener("click", () => set(r.copie - 1));
  $(".piu", el).addEventListener("click", () => set(r.copie + 1));
  copie.addEventListener("input", () => { if (copie.value !== "") set(parseInt(copie.value, 10)); });
  copie.addEventListener("blur", () => set(parseInt(copie.value, 10)));
  copie.addEventListener("focus", () => copie.select());
  $(".rm-riga", el).addEventListener("click", () => {
    art.righe.splice(ri, 1);
    sel = { a: ai, r: Math.max(0, Math.min(sel.r, art.righe.length - 1)) };
    render(); cambiato();
  });
  return el;
}

function selezione(a, r) {
  if (sel.a === a && sel.r === r) return;
  sel = { a, r };
  evidenzia(); anteprima();
}

function evidenzia() {
  $$(".riga").forEach(el => el.classList.toggle("is-sel", +el.dataset.a === sel.a && +el.dataset.r === sel.r));
}

function totale() {
  return stato.articoli.reduce((s, a) => s + a.righe.reduce((t, r) => t + (r.taglia.trim() ? r.copie : 0), 0), 0);
}

function aggiornaTotali() {
  stato.articoli.forEach((a, ai) => {
    const card = $(`.articolo[data-a="${ai}"]`);
    if (!card) return;
    const n = a.righe.reduce((t, r) => t + (r.taglia.trim() ? r.copie : 0), 0);
    $(".articolo-tot", card).textContent = `${n} ${n === 1 ? "etichetta" : "etichette"}`;
  });
  const n = totale();
  $("#tot").textContent = n;
  const b = $("#stampa");
  b.textContent = `Stampa ${n} ${n === 1 ? "etichetta" : "etichette"}`;
  b.disabled = n === 0;
  $("#pdf").disabled = n === 0;
}

let tCambio;
function cambiato() {
  aggiornaTotali();
  salvaBozza();
  clearTimeout(tCambio);
  tCambio = setTimeout(anteprima, 250);
}

// ------------------------------------------------------------------ anteprima
let ultimaAnteprima = "";
function anteprima() {
  const art = stato.articoli[sel.a] || stato.articoli[0];
  const riga = art?.righe[sel.r] || art?.righe[0];
  const p = new URLSearchParams({
    commessa: stato.nome.trim(),
    articolo: (art?.descrizione || "").trim(),
    taglia: (riga?.taglia || "").trim(),
  });
  if (impostazioni.contatore) {
    const pos = posizioneInStampa(sel.a, sel.r);
    if (pos) { p.set("i", pos.i); p.set("n", pos.n); }
  }
  const url = "/api/anteprima.png?" + p;
  if (url === ultimaAnteprima) return;
  ultimaAnteprima = url;
  $("#preview").src = url;
  $("#preview-label").textContent = riga ? `${riga.taglia || "—"} · ${art.descrizione || "senza descrizione"}` : "";
}

// stesso ordine di app/jobs.py: bimbo < XS…3XL < 4XL, 5XL… < altre
function chiaveTaglia(t) {
  t = t.trim().toUpperCase();
  const i = TAGLIE.indexOf(t);
  if (i >= 0) return [1, i, 0];
  let m = t.match(/^(\d+)\s*XL$/);
  if (m) return [1, TAGLIE.length - 1 + (+m[1]) - 3, 0];
  m = t.match(/^(X{3,})L$/);
  if (m) return [1, TAGLIE.length - 1 + m[1].length - 3, 0];
  m = t.match(/^(\d+)(?:\s*[-/]\s*(\d+))?\s*(?:A|ANNI|Y)?$/);
  if (m) return [0, +m[1], +(m[2] || m[1])];
  return [2, 0, 0];
}

// indice (1-based) della prima etichetta di quella riga nell'ordine di stampa
function posizioneInStampa(a, r) {
  const ord = chiaveTaglia;
  let n = 0, trovato = null;
  stato.articoli.forEach((art, ai) => {
    art.righe.map((x, ri) => ({ x, ri }))
      .filter(o => o.x.taglia.trim() && o.x.copie > 0)
      .sort((p, q) => { const A = ord(p.x.taglia), B = ord(q.x.taglia); return A[0] - B[0] || A[1] - B[1] || A[2] - B[2] || p.ri - q.ri; })
      .forEach(o => { if (ai === a && o.ri === r) trovato = n + 1; n += o.x.copie; });
  });
  return trovato ? { i: trovato, n } : null;
}

// ------------------------------------------------------------------ PDF
async function scaricaPdf() {
  const c = commessaPulita();
  try {
    const res = await api("/api/pdf", { json: c });
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    const cd = res.headers.get("Content-Disposition") || "";
    a.download = (cd.match(/filename="([^"]+)"/) || [])[1] || "etichette.pdf";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ conferma + stampa
async function apriConferma() {
  const c = commessaPulita();
  let r;
  try { r = await (await api("/api/riepilogo", { json: c })).json(); }
  catch (e) { return toast(e.message, true); }
  $("#sheet-title").textContent = "Conferma stampa";
  $("#sheet-sub").textContent = `${c.nome || "Commessa senza nome"} · ${r.totale} etichette, in quest'ordine:`;
  $("#sheet-body").innerHTML = tabellaRiepilogo(r);
  const warn = $("#sheet-warn");
  warn.hidden = !r.richiede_conferma_extra;
  warn.textContent = r.richiede_conferma_extra
    ? `Attenzione: ${r.totale} etichette sono più di 200. Controlla bene prima di confermare.` : "";
  azioniConferma(c, r, false);
  apriSheet();
}

function azioniConferma(c, r, secondaConferma) {
  const box = $("#sheet-actions");
  box.textContent = "";
  const ok = bottone(secondaConferma ? `Sì, stampa ${r.totale} etichette` : "Conferma e stampa", "btn btn-primary btn-wide");
  ok.addEventListener("click", () => {
    if (r.richiede_conferma_extra && !secondaConferma) return azioniConferma(c, r, true);
    avviaStampa(c, 1, r.richiede_conferma_extra);
  });
  box.append(ok, bottoneChiudi("Annulla"));
  if (secondaConferma) $("#sheet-warn").textContent = `Seconda conferma: stai per stampare ${r.totale} etichette.`;
}

function tabellaRiepilogo(r) {
  let h = "<table><thead><tr><th>Taglia</th><th class='n'>Copie</th><th class='n'>N.</th></tr></thead><tbody>";
  let art = -1;
  for (const g of r.righe) {
    if (g.articolo !== art) {
      art = g.articolo;
      const tot = r.articoli[art].totale;
      h += `<tr class="art"><td>${esc(g.descrizione || `Articolo ${art + 1}`)}</td><td class="n">${tot}</td><td></td></tr>`;
    }
    h += `<tr><td class="sz">${esc(g.taglia)}</td><td class="n">${g.copie}</td><td class="n muted">${g.da === g.a ? g.da : g.da + "–" + g.a}</td></tr>`;
  }
  return h + "</tbody></table>";
}

let pollTimer;
async function avviaStampa(c, daIndice, confermaExtra) {
  let job;
  try {
    job = await (await api("/api/stampa", { json: { commessa: c, da_indice: daIndice, conferma_extra: !!confermaExtra } })).json();
  } catch (e) {
    if (e.status === 404 || e.status === 405) return mostraErroreStampa("La stampa di rete non è ancora attiva in questa versione. Usa \"Scarica PDF\".", c);
    return mostraErroreStampa(e.message, c);
  }
  mostraAvanzamento(job, c);
}

function mostraAvanzamento(job, c) {
  $("#sheet-title").textContent = "Stampa in corso";
  $("#sheet-warn").hidden = true;
  $("#sheet-body").innerHTML = `<div class="progress"><div id="prog"></div></div><p id="prog-txt"></p>`;
  const box = $("#sheet-actions"); box.textContent = "";
  const stop = bottone("Interrompi", "btn btn-outline btn-wide");
  stop.addEventListener("click", () => api(`/api/stampa/${job.id}/annulla`, { method: "POST" }).catch(() => {}));
  box.append(stop);
  clearInterval(pollTimer);
  const tick = async () => {
    let s;
    try { s = await (await api(`/api/stampa/${job.id}`)).json(); }
    catch (e) { clearInterval(pollTimer); return mostraErroreStampa(e.message, c); }
    const pct = s.totale ? Math.round(100 * s.inviate / s.totale) : 0;
    $("#prog").style.width = pct + "%";
    $("#prog-txt").textContent = `Etichetta ${s.inviate} di ${s.totale}`;
    if (s.stato === "completato") {
      clearInterval(pollTimer);
      $("#sheet-title").textContent = "Stampa completata";
      $("#sheet-sub").textContent = `${s.totale} etichette inviate alla stampante.`;
      box.textContent = "";
      box.append(bottoneChiudi("Fatto", "btn btn-primary btn-wide"));
    } else if (s.stato === "errore" || s.stato === "annullato") {
      clearInterval(pollTimer);
      mostraErroreStampa(s.errore || "Stampa interrotta.", c, s.prossimo_indice, s.totale);
    }
  };
  tick(); pollTimer = setInterval(tick, 700);
}

function mostraErroreStampa(msg, c, prossimo, tot) {
  $("#sheet-title").textContent = "Stampa non riuscita";
  const warn = $("#sheet-warn"); warn.hidden = false; warn.textContent = msg;
  const box = $("#sheet-actions"); box.textContent = "";
  if (prossimo && tot && prossimo <= tot) {
    $("#sheet-body").insertAdjacentHTML("beforeend",
      `<label class="field"><span class="field-label">Riprendi dall'etichetta</span>
       <input id="riprendi-da" type="number" inputmode="numeric" min="1" max="${tot}" value="${prossimo}"></label>`);
    const rip = bottone("Riprendi stampa", "btn btn-primary btn-wide");
    rip.addEventListener("click", () => {
      const da = Math.max(1, Math.min(tot, parseInt($("#riprendi-da").value, 10) || prossimo));
      avviaStampa(c, da, tot - da + 1 > 200);
    });
    box.append(rip);
  }
  box.append(bottoneChiudi("Chiudi"));
}

function bottone(txt, cls) { const b = document.createElement("button"); b.type = "button"; b.className = cls; b.textContent = txt; return b; }
function bottoneChiudi(txt, cls = "btn btn-outline btn-wide") { const b = bottone(txt, cls); b.addEventListener("click", chiudiSheet); return b; }
function apriSheet() { $("#sheet").hidden = false; }
function chiudiSheet() { clearInterval(pollTimer); $("#sheet").hidden = true; }

// ------------------------------------------------------------------ PIN
let pinPromise = null;
function chiediPin() {
  if (pinPromise) return pinPromise;
  pinPromise = new Promise(resolve => {
    const sh = $("#pin-sheet"); sh.hidden = false; $("#pin-input").value = ""; $("#pin-input").focus();
    $("#pin-form").onsubmit = async ev => {
      ev.preventDefault();
      try {
        await api("/api/accesso", { json: { pin: $("#pin-input").value } });
        sh.hidden = true; pinPromise = null; resolve();
      } catch (e) { $("#pin-err").textContent = e.message; }
    };
  });
  return pinPromise;
}

// ------------------------------------------------------------------ impostazioni
async function caricaImpostazioni() {
  try { impostazioni = await (await api("/api/impostazioni")).json(); } catch (_) { impostazioni = {}; }
  const f = $("#form-imp");
  f.ip_stampante.value = impostazioni.ip_stampante || "";
  f.modello.value = impostazioni.modello || "QL-810W";
  f.etichetta.value = impostazioni.etichetta || "62x100";
  f.contatore.checked = !!impostazioni.contatore;
  f.mostra_commessa.checked = impostazioni.mostra_commessa !== false;
  f.pin.value = "";
  $("#pin-stato").textContent = impostazioni.pin_attivo ? "PIN attivo. Scrivi un nuovo PIN per cambiarlo." : "Nessun PIN impostato.";
  $("#togli-pin").hidden = !impostazioni.pin_attivo;
  $("#top-sub").textContent = impostazioni.ip_stampante ? `Stampante ${impostazioni.ip_stampante}` : "Stampante non configurata";
}

async function salvaImpostazioni(ev) {
  ev.preventDefault();
  const f = ev.target;
  const body = {
    ip_stampante: f.ip_stampante.value.trim(), modello: f.modello.value, etichetta: f.etichetta.value,
    contatore: f.contatore.checked, mostra_commessa: f.mostra_commessa.checked,
  };
  const pin = f.pin.value.trim();
  if (pin) body.pin = pin;
  try {
    await api("/api/impostazioni", { method: "PUT", json: body });
    await caricaImpostazioni();
    ultimaAnteprima = ""; anteprima();
    toast("Impostazioni salvate");
  } catch (e) { toast(e.message, true); }
}

async function verificaStampante() {
  const pill = $("#stato-stampante");
  pill.className = "pill"; pill.textContent = "Verifico…";
  try {
    const s = await (await api("/api/stampante/stato")).json();
    pill.className = "pill " + (s.raggiungibile ? "ok" : "ko");
    pill.textContent = s.messaggio || (s.raggiungibile ? "Stampante raggiungibile" : "Non raggiungibile");
  } catch (e) {
    pill.className = "pill ko";
    pill.textContent = e.status === 404 ? "Verifica disponibile con la stampa di rete" : e.message;
  }
}

async function stampaProva() {
  try { await api("/api/stampante/prova", { method: "POST" }); toast("Etichetta di prova inviata"); }
  catch (e) { toast(e.status === 404 ? "Stampa di rete non ancora attiva" : e.message, true); }
}

// ------------------------------------------------------------------ viste
function vista(nome) {
  $$(".view").forEach(v => v.hidden = v.id !== "v-" + nome);
  $$(".tab").forEach(t => t.classList.toggle("is-active", t.dataset.view === nome));
  const conBarra = nome === "nuova";
  $("#actionbar").hidden = !conBarra;
  document.body.classList.toggle("no-bar", !conBarra);
  if (nome === "impostazioni") caricaImpostazioni();
  if (nome === "storico" && window.FFStorico) window.FFStorico.carica();
  try { history.replaceState(null, "", "#" + nome); } catch (_) {}
  window.scrollTo(0, 0);
}

async function caricaInfo() {
  if (window.matchMedia("(max-width: 899px)").matches) return;
  try {
    const d = await (await api("/api/info")).json();
    $("#qr").innerHTML = d.qr_svg;
    $("#lan-url").textContent = d.url;
    $("#qr-card").hidden = false;
  } catch (_) {}
}

let tToast;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.classList.toggle("is-err", err); t.hidden = false;
  clearTimeout(tToast); tToast = setTimeout(() => t.hidden = true, err ? 5000 : 2500);
}

function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

// API per altri moduli (storico)
window.FF = {
  carica(c) { stato = c; sel = { a: 0, r: 0 }; render(); cambiato(); vista("nuova"); },
  api, toast, esc, apriSheet, chiudiSheet, tabellaRiepilogo, avviaStampa,
};

// ------------------------------------------------------------------ avvio
document.addEventListener("DOMContentLoaded", async () => {
  $("#commessa").addEventListener("input", e => { stato.nome = e.target.value; cambiato(); });
  $("#add-articolo").addEventListener("click", () => {
    stato.articoli.push({ descrizione: "", righe: [{ taglia: "M", copie: 1 }] });
    sel = { a: stato.articoli.length - 1, r: 0 };
    render(); cambiato();
    $$(".articolo .descrizione").pop()?.focus();
  });
  $("#svuota").addEventListener("click", () => {
    if (totale() && !confirm("Svuotare la commessa in corso?")) return;
    stato = nuovaCommessa(); sel = { a: 0, r: 0 }; render(); cambiato();
  });
  $("#pdf").addEventListener("click", scaricaPdf);
  $("#stampa").addEventListener("click", apriConferma);
  $("#form-imp").addEventListener("submit", salvaImpostazioni);
  $("#verifica").addEventListener("click", verificaStampante);
  $("#prova").addEventListener("click", stampaProva);
  $("#togli-pin").addEventListener("click", async () => {
    if (!confirm("Togliere il PIN? L'app sarà accessibile a tutti sulla rete locale.")) return;
    try { await api("/api/impostazioni", { method: "PUT", json: { pin: "" } }); await caricaImpostazioni(); toast("PIN rimosso"); }
    catch (e) { toast(e.message, true); }
  });
  $("#sheet").addEventListener("click", e => { if (e.target.id === "sheet" && !$("#prog")) chiudiSheet(); });
  $$(".tab").forEach(t => t.addEventListener("click", () => vista(t.dataset.view)));

  render();
  await caricaImpostazioni();
  anteprima();
  caricaInfo();
  const h = (location.hash || "").slice(1);
  vista(["nuova", "storico", "impostazioni"].includes(h) ? h : "nuova");

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
});
