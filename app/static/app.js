/* FF Etichette — frontend senza build. */
"use strict";

const TAGLIE = ["XS", "S", "M", "L", "XL", "XXL", "3XL"];
const BOZZA_KEY = "ff-etichette-bozza";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

let stato = caricaBozza() || nuovaCommessa();
let sel = { a: 0, r: 0 };           // riga selezionata per l'anteprima
let impostazioni = {};

// tipo "capo": un'etichetta per busta; "ordine": etichetta riepilogo dell'intero ordine.
// _storicoId / _salvata: la commessa è stata salvata per dopo (id nello storico, dati salvati)
function nuovaCommessa(tipo = "capo") {
  return { nome: "", tipo, copie_ordine: 1, numera_colli: false,
           articoli: [{ descrizione: "", righe: [{ taglia: "M", copie: 1 }] }] };
}
const eOrdine = () => stato.tipo === "ordine";

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
    tipo: stato.tipo,
    copie_ordine: stato.copie_ordine,
    numera_colli: stato.numera_colli,
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
    if (s && Array.isArray(s.articoli)) return { ...nuovaCommessa(), ...s };
  } catch (_) {}
  return null;
}

// ------------------------------------------------------------------ rendering form
function render() {
  $("#commessa").value = stato.nome;
  renderTipo();
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
  aggiornaBozzaInfo();
}

function renderTipo() {
  $$(".segmented button").forEach(b => {
    const on = b.dataset.tipo === stato.tipo;
    b.classList.toggle("is-on", on); b.setAttribute("aria-checked", on);
  });
  $("#ordine-opzioni").hidden = !eOrdine();
  $("#copie-ordine").value = stato.copie_ordine;
  $("#numera-colli").checked = !!stato.numera_colli;
}

function setTipo(t) {
  if (t === stato.tipo) return;
  stato.tipo = t; foglio = 1;
  ultimaAnteprima = ""; ultimaOrdine = "";
  render(); cambiato();
}

function aggiornaBozzaInfo() {
  const el = $("#bozza-info");
  if (!stato._storicoId) { el.hidden = true; return; }
  const mod = JSON.stringify(commessaPulita()) !== stato._salvata;
  el.hidden = false;
  el.classList.toggle("is-mod", mod);
  el.textContent = mod
    ? "Commessa salvata per dopo: ci sono modifiche non ancora salvate."
    : "Commessa salvata per dopo: la trovi in Storico › Da stampare.";
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
  const ordine = eOrdine();
  stato.articoli.forEach((a, ai) => {
    const card = $(`.articolo[data-a="${ai}"]`);
    if (!card) return;
    const n = a.righe.reduce((t, r) => t + (r.taglia.trim() ? r.copie : 0), 0);
    $(".articolo-tot", card).textContent = ordine ? `${n} ${n === 1 ? "capo" : "capi"}`
                                                  : `${n} ${n === 1 ? "etichetta" : "etichette"}`;
  });
  const capi = totale();
  // in modalità ordine: copie x fogli del riepilogo (i fogli arrivano dall'anteprima)
  const n = ordine ? (capi ? stato.copie_ordine * fogliOrdine : 0) : capi;
  $("#tot").textContent = n;
  $(".actionbar-total span").textContent = ordine ? `etichette · ${capi} capi` : "etichette";
  const b = $("#stampa");
  b.textContent = `Stampa ${n} ${n === 1 ? "etichetta" : "etichette"}`;
  b.disabled = n === 0;
  $("#pdf").disabled = n === 0;
}

let tCambio;
function cambiato() {
  aggiornaTotali();
  aggiornaBozzaInfo();
  salvaBozza();
  clearTimeout(tCambio);
  tCambio = setTimeout(anteprima, 250);
}

// ------------------------------------------------------------------ anteprima
let ultimaAnteprima = "";
function anteprima() {
  if (eOrdine()) return anteprimaOrdine();
  $("#pager").hidden = true;
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

// anteprima dell'etichetta riepilogo: serve l'intera commessa, quindi POST
let foglio = 1, fogliOrdine = 1, ultimaOrdine = "", urlOrdine = null;
async function anteprimaOrdine() {
  const c = commessaPulita();
  const key = JSON.stringify(c) + "|" + foglio;
  if (key === ultimaOrdine) return;
  ultimaOrdine = key;
  let res, blob;
  try {
    res = await api("/api/anteprima-ordine.png?foglio=" + foglio, { json: c });
    blob = await res.blob();
  } catch (_) { ultimaOrdine = ""; return; }
  if (key !== ultimaOrdine) return;                 // nel frattempo è cambiato qualcosa
  fogliOrdine = parseInt(res.headers.get("X-Fogli"), 10) || 1;
  foglio = Math.min(foglio, fogliOrdine);
  if (urlOrdine) URL.revokeObjectURL(urlOrdine);
  urlOrdine = URL.createObjectURL(blob);
  $("#preview").src = urlOrdine;
  const capi = totale();
  $("#preview-label").textContent = fogliOrdine > 1 ? `Foglio ${foglio} di ${fogliOrdine}` : `${capi} ${capi === 1 ? "capo" : "capi"}`;
  $("#pager").hidden = fogliOrdine <= 1;
  $("#foglio-prec").disabled = foglio <= 1;
  $("#foglio-succ").disabled = foglio >= fogliOrdine;
  aggiornaTotali();
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
  if (r.tipo === "ordine") {
    const fogli = r.fogli > 1 ? ` × ${r.fogli} fogli` : "";
    $("#sheet-sub").textContent = `${c.nome || "Commessa senza nome"} · ${r.totale} ${r.totale === 1 ? "etichetta" : "etichette"} riepilogo ` +
      `(${r.copie} ${r.copie === 1 ? "copia" : "copie"}${fogli}) per ${r.capi} capi:`;
    $("#sheet-body").innerHTML = tabellaOrdine(r);
  } else {
    $("#sheet-sub").textContent = `${c.nome || "Commessa senza nome"} · ${r.totale} etichette, in quest'ordine:`;
    $("#sheet-body").innerHTML = tabellaRiepilogo(r);
  }
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
    avviaStampa(c, 1, r.richiede_conferma_extra, stato._storicoId ?? null, !!stato._storicoId);
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

function tabellaOrdine(r) {
  let h = "<table><thead><tr><th>Taglia</th><th class='n'>Capi</th></tr></thead><tbody>";
  let art = -1;
  for (const g of r.righe) {
    if (g.articolo !== art) {
      art = g.articolo;
      h += `<tr class="art"><td>${esc(g.descrizione || `Articolo ${art + 1}`)}</td><td class="n">${r.articoli[art].totale}</td></tr>`;
    }
    h += `<tr><td class="sz">${esc(g.taglia)}</td><td class="n">${g.capi}</td></tr>`;
  }
  return h + "</tbody></table>";
}

let pollTimer;
// aggiorna: la commessa nel modulo è stata salvata per dopo (storicoId): la stampa la aggiorna
async function avviaStampa(c, daIndice, confermaExtra, storicoId = null, aggiorna = false) {
  let job;
  try {
    job = await (await api("/api/stampa", { json: { commessa: c, da_indice: daIndice, conferma_extra: !!confermaExtra,
                                                    storico_id: storicoId, aggiorna_bozza: aggiorna } })).json();
  } catch (e) {
    return mostraErroreStampa(e.message, c);
  }
  if (aggiorna) {                 // stampata: non è più "da stampare", il modulo se ne stacca
    delete stato._storicoId; delete stato._salvata;
    salvaBozza(); aggiornaBozzaInfo();
  }
  if (window.FFStorico) window.FFStorico.invalida();
  mostraAvanzamento(job, c);
}

// ------------------------------------------------------------------ salva per dopo
async function salvaPerDopo() {
  const c = commessaPulita();
  if (!c.articoli.length) return toast("Niente da salvare: aggiungi almeno una taglia.", true);
  const id = stato._storicoId;
  let r;
  try {
    r = await (await api(id ? `/api/storico/${id}` : "/api/storico", { method: id ? "PUT" : "POST", json: c })).json();
  } catch (e) { return toast(e.message, true); }
  stato._storicoId = r.id; stato._salvata = JSON.stringify(c);
  salvaBozza(); aggiornaBozzaInfo();
  if (window.FFStorico) window.FFStorico.invalida();
  toast(id && r.nuova ? "Era già stata stampata: salvata come nuova commessa da stampare"
                      : "Salvata per dopo: la trovi in Storico › Da stampare");
}

// ------------------------------------------------------------------ import da file
async function importaFile(file) {
  if (!file) return;
  if (totale() && !confirm("Sostituire la commessa nel modulo con quella del file?")) return;
  const fd = new FormData(); fd.append("file", file);
  let d;
  try { d = await (await api("/api/import", { method: "POST", body: fd })).json(); }
  catch (e) { return toast(e.message, true); }
  const c = d.commessa;
  stato = { ...nuovaCommessa(stato.tipo), nome: c.nome, articoli: c.articoli,
            copie_ordine: stato.copie_ordine, numera_colli: stato.numera_colli };
  sel = { a: 0, r: 0 }; foglio = 1;
  render(); cambiato();
  const capi = totale();
  const msg = `Importati ${c.articoli.length} ${c.articoli.length === 1 ? "articolo" : "articoli"} e ${capi} capi da ${file.name}. Controlla prima di stampare.`;
  if (!d.avvisi.length) return toast(msg);
  $("#sheet-title").textContent = "File importato";
  $("#sheet-sub").textContent = msg;
  $("#sheet-warn").hidden = true;
  $("#sheet-body").innerHTML = `<h3>Da controllare</h3><ul class="stampe">${d.avvisi.map(a => `<li>${esc(a)}</li>`).join("")}</ul>`;
  const box = $("#sheet-actions"); box.textContent = "";
  box.append(bottoneChiudi("Ho capito", "btn btn-primary btn-wide"));
  apriSheet();
}

function mostraAvanzamento(job, c) {
  $("#sheet-title").textContent = "Stampa in corso";
  $("#sheet-sub").textContent = `${c.nome || "Commessa senza nome"} · ${job.totale} etichette`;
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
    $("#prog-txt").textContent = s.preparazione && s.stato === "in_corso"
      ? "Preparo le etichette…" : `Etichetta ${s.inviate} di ${s.totale}`;
    if (s.stato === "completato") {
      clearInterval(pollTimer);
      if (window.FFStorico) window.FFStorico.invalida();
      $("#sheet-title").textContent = "Stampa completata";
      $("#sheet-sub").textContent = `${s.totale} etichette inviate alla stampante.`;
      box.textContent = "";
      box.append(bottoneChiudi("Fatto", "btn btn-primary btn-wide"));
    } else if (s.stato === "errore" || s.stato === "annullato") {
      clearInterval(pollTimer);
      mostraErroreStampa(s.errore || "Stampa interrotta.", c, s.prossimo_indice, s.totale, s.commessa_id);
    }
  };
  tick(); pollTimer = setInterval(tick, 700);
}

function mostraErroreStampa(msg, c, prossimo, tot, storicoId = null) {
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
      avviaStampa(c, da, tot - da + 1 > 200, storicoId);
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
  f.compensazione.value = String(impostazioni.compensazione ?? 0.25);
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
    compensazione: parseFloat(f.compensazione.value),
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

async function stampaProva(percorso = "/api/stampante/prova") {
  let job;
  try { job = await (await api(percorso, { method: "POST" })).json(); }
  catch (e) { return toast(e.message, true); }
  toast("Prova inviata alla stampante…");
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 500));
    let s;
    try { s = await (await api(`/api/stampa/${job.id}`)).json(); } catch (e) { return toast(e.message, true); }
    if (s.stato === "completato") return toast(s.totale > 1 ? `${s.totale} etichette di prova stampate` : "Etichetta di prova stampata");
    if (s.stato === "errore" || s.stato === "annullato") return toast(s.errore || "Stampa non riuscita", true);
  }
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
  // storicoId: commessa salvata per dopo, aperta per modificarla o stamparla
  carica(c, storicoId = null) {
    stato = { ...nuovaCommessa(), ...c };
    delete stato._storicoId; delete stato._salvata;
    if (storicoId) { stato._storicoId = storicoId; stato._salvata = JSON.stringify(commessaPulita()); }
    sel = { a: 0, r: 0 }; foglio = 1; ultimaOrdine = ""; ultimaAnteprima = "";
    render(); cambiato(); vista("nuova");
  },
  api, toast, esc, apriSheet, chiudiSheet, tabellaRiepilogo, tabellaOrdine, avviaStampa, apriConferma,
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
    const msg = stato._storicoId ? "Svuotare il modulo? La commessa salvata per dopo resta nello storico."
                                 : "Svuotare la commessa in corso?";
    if (totale() && !confirm(msg)) return;
    stato = nuovaCommessa(stato.tipo); sel = { a: 0, r: 0 }; foglio = 1; render(); cambiato();
  });
  $$(".segmented button").forEach(b => b.addEventListener("click", () => setTipo(b.dataset.tipo)));
  const setCopie = v => {
    stato.copie_ordine = Math.max(1, Math.min(99, Number.isFinite(v) ? Math.round(v) : 1));
    $("#copie-ordine").value = stato.copie_ordine; cambiato();
  };
  $("#copie-meno").addEventListener("click", () => setCopie(stato.copie_ordine - 1));
  $("#copie-piu").addEventListener("click", () => setCopie(stato.copie_ordine + 1));
  $("#copie-ordine").addEventListener("input", e => { if (e.target.value !== "") setCopie(parseInt(e.target.value, 10)); });
  $("#copie-ordine").addEventListener("blur", e => setCopie(parseInt(e.target.value, 10)));
  $("#copie-ordine").addEventListener("focus", e => e.target.select());
  $("#numera-colli").addEventListener("change", e => { stato.numera_colli = e.target.checked; cambiato(); });
  $("#foglio-prec").addEventListener("click", () => { foglio = Math.max(1, foglio - 1); anteprimaOrdine(); });
  $("#foglio-succ").addEventListener("click", () => { foglio = Math.min(fogliOrdine, foglio + 1); anteprimaOrdine(); });
  $("#salva-dopo").addEventListener("click", salvaPerDopo);
  $("#importa").addEventListener("click", () => $("#file-import").click());
  $("#file-import").addEventListener("change", async e => { await importaFile(e.target.files[0]); e.target.value = ""; });
  $("#pdf").addEventListener("click", scaricaPdf);
  $("#stampa").addEventListener("click", apriConferma);
  $("#form-imp").addEventListener("submit", salvaImpostazioni);
  $("#verifica").addEventListener("click", verificaStampante);
  $("#prova").addEventListener("click", () => stampaProva());
  $("#prova-comp").addEventListener("click", () => stampaProva("/api/stampante/prova-compensazione"));
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
