/* Storico: cerca, apri, duplica, ristampa tutto o solo alcune righe.
   Le commesse "salvate per dopo" (mai stampate) si stampano, si modificano o si eliminano. */
"use strict";
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  let tCerca, aggiornare = true, filtro = "";

  const dataIt = iso => {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric" }) +
      " " + d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  };
  const ESITO = { completato: "Stampata", errore: "Interrotta", annullato: "Interrotta", in_corso: "In corso" };

  async function carica() {
    const q = $("#cerca").value.trim();
    const box = $("#storico-lista");
    let lista;
    const p = new URLSearchParams({ q, stato: filtro });
    try { lista = await (await FF.api("/api/storico?" + p)).json(); }
    catch (e) { box.innerHTML = `<p class="err">${FF.esc(e.message)}</p>`; return; }
    aggiornare = false;
    if (!lista.length) {
      const vuoto = q ? "Nessuna commessa trovata."
        : filtro === "bozze" ? "Nessuna commessa da stampare. Usa «Salva per dopo» in fondo al modulo."
        : "Nessuna commessa finora.";
      box.innerHTML = `<p class="muted">${vuoto}</p>`;
      return;
    }
    box.innerHTML = lista.map(c => `
      <button class="storico-item" type="button" data-id="${c.id}">
        <span class="si-top"><strong>${FF.esc(c.nome || "Senza nome")}</strong><span class="si-n">${c.totale}${c.tipo === "ordine" ? " capi" : ""}</span></span>
        <span class="si-art">${FF.esc(c.articoli.filter(Boolean).join(" · ") || "—")}</span>
        <span class="si-meta">${c.bozza ? "Salvata il " : ""}${dataIt(c.ultima_stampa || c.creata)}${c.n_stampe > 1 ? ` · ${c.n_stampe} stampe` : ""}
          ${c.bozza ? `<span class="si-tag da-stampare">Da stampare</span>` : ""}
          ${c.tipo === "ordine" ? `<span class="si-tag">Riepilogo ordine</span>` : ""}
          ${c.esito && c.esito !== "completato" ? `<span class="si-warn">${ESITO[c.esito] || c.esito}</span>` : ""}</span>
      </button>`).join("");
  }

  // commessa salvata per dopo: niente selezione di righe, si stampa, si modifica o si elimina
  function apriBozza(d) {
    const c = d.commessa, ordine = c.tipo === "ordine";
    $("#sheet-title").textContent = c.nome || "Commessa senza nome";
    $("#sheet-sub").textContent = `Salvata il ${dataIt(d.creata)} · ${ordine ? "riepilogo ordine" : "un'etichetta per capo"} · ` +
      `${totale(c)} ${ordine ? "capi" : "etichette"}${ordine ? ` · ${c.copie_ordine || 1} ${c.copie_ordine > 1 ? "copie" : "copia"}` : ""}`;
    $("#sheet-warn").hidden = true;
    let h = `<table><thead><tr><th>Taglia</th><th class="n">${ordine ? "Capi" : "Copie"}</th></tr></thead><tbody>`;
    c.articoli.forEach((a, ai) => {
      h += `<tr class="art"><td>${FF.esc(a.descrizione || "Articolo " + (ai + 1))}</td><td class="n">${a.righe.reduce((s, r) => s + r.copie, 0)}</td></tr>`;
      a.righe.forEach(r => { h += `<tr><td class="sz">${FF.esc(r.taglia)}</td><td class="n">${r.copie}</td></tr>`; });
    });
    $("#sheet-body").innerHTML = h + "</tbody></table>";

    const box = $("#sheet-actions"); box.textContent = "";
    const b = (txt, cls, fn) => {
      const x = document.createElement("button");
      x.type = "button"; x.className = cls; x.textContent = txt; x.addEventListener("click", fn);
      box.append(x);
    };
    b("Stampa", "btn btn-primary btn-wide", () => { FF.chiudiSheet(); FF.carica(c, d.id); FF.apriConferma(); });
    b("Modifica", "btn btn-outline btn-wide", () => { FF.chiudiSheet(); FF.carica(c, d.id); });
    b("Elimina", "btn btn-ghost btn-wide", async () => {
      if (!confirm(`Eliminare «${c.nome || "Commessa senza nome"}» dalle commesse da stampare?`)) return;
      try { await FF.api("/api/storico/" + d.id, { method: "DELETE" }); }
      catch (e) { return FF.toast(e.message, true); }
      FF.chiudiSheet(); FF.toast("Commessa eliminata"); carica();
    });
    b("Chiudi", "btn btn-outline btn-wide", FF.chiudiSheet);
    FF.apriSheet();
  }

  // riepilogo ordine già stampato: si ristampa tutto (le righe non si scelgono)
  async function apriOrdine(d) {
    const c = d.commessa;
    let r;
    try { r = await (await FF.api("/api/riepilogo", { json: c })).json(); } catch (e) { return FF.toast(e.message, true); }
    $("#sheet-title").textContent = c.nome || "Commessa senza nome";
    $("#sheet-sub").textContent = `Riepilogo ordine · ${r.capi} capi · ${r.totale} ${r.totale === 1 ? "etichetta" : "etichette"}`;
    $("#sheet-warn").hidden = true;
    let h = FF.tabellaOrdine(r);
    if (d.stampe.length) {
      h += `<h3>Stampe</h3><ul class="stampe">` + d.stampe.map(s =>
        `<li>${dataIt(s.data)} · ${s.totale} etichette${s.da_indice > 1 ? ` (da ${s.da_indice})` : ""} · <strong>${ESITO[s.stato] || s.stato}</strong>${s.errore ? `<br><span class="muted">${FF.esc(s.errore)}</span>` : ""}</li>`).join("") + "</ul>";
    }
    $("#sheet-body").innerHTML = h;
    const box = $("#sheet-actions"); box.textContent = "";
    const ristampa = document.createElement("button");
    ristampa.type = "button"; ristampa.className = "btn btn-primary btn-wide";
    ristampa.textContent = `Ristampa (${r.totale} ${r.totale === 1 ? "etichetta" : "etichette"})`;
    ristampa.addEventListener("click", () => FF.avviaStampa(c, 1, r.totale > 200, d.id));
    const duplica = document.createElement("button");
    duplica.type = "button"; duplica.className = "btn btn-outline btn-wide"; duplica.textContent = "Duplica e modifica";
    duplica.addEventListener("click", () => {
      FF.chiudiSheet(); FF.carica(JSON.parse(JSON.stringify(c))); FF.toast("Commessa copiata: modificala e stampa");
    });
    const chiudi = document.createElement("button");
    chiudi.type = "button"; chiudi.className = "btn btn-outline btn-wide"; chiudi.textContent = "Chiudi";
    chiudi.addEventListener("click", FF.chiudiSheet);
    box.append(ristampa, duplica, chiudi);
    FF.apriSheet();
  }

  async function apri(id) {
    let d;
    try { d = await (await FF.api("/api/storico/" + id)).json(); } catch (e) { return FF.toast(e.message, true); }
    if (d.bozza) return apriBozza(d);
    if (d.commessa.tipo === "ordine") return apriOrdine(d);
    const c = d.commessa;
    $("#sheet-title").textContent = c.nome || "Commessa senza nome";
    $("#sheet-sub").textContent = `Creata il ${dataIt(d.creata)} · ${totale(c)} etichette`;
    $("#sheet-warn").hidden = true;

    let h = `<p class="muted">Spunta le righe da ristampare.</p><table><thead><tr><th></th><th>Taglia</th><th class="n">Copie</th></tr></thead><tbody>`;
    c.articoli.forEach((a, ai) => {
      h += `<tr class="art"><td><input type="checkbox" class="sel-art" data-a="${ai}" checked aria-label="Tutto l'articolo"></td><td>${FF.esc(a.descrizione || "Articolo " + (ai + 1))}</td><td class="n">${a.righe.reduce((s, r) => s + r.copie, 0)}</td></tr>`;
      a.righe.forEach((r, ri) => {
        h += `<tr><td><input type="checkbox" class="sel-riga" data-a="${ai}" data-r="${ri}" checked aria-label="${FF.esc(r.taglia)}"></td><td class="sz">${FF.esc(r.taglia)}</td><td class="n">${r.copie}</td></tr>`;
      });
    });
    h += "</tbody></table>";
    if (d.stampe.length) {
      h += `<h3>Stampe</h3><ul class="stampe">` + d.stampe.map(s =>
        `<li>${dataIt(s.data)} · ${s.totale} etichette${s.da_indice > 1 ? ` (da ${s.da_indice})` : ""} · <strong>${ESITO[s.stato] || s.stato}</strong>${s.errore ? `<br><span class="muted">${FF.esc(s.errore)}</span>` : ""}</li>`).join("") + "</ul>";
    }
    $("#sheet-body").innerHTML = h;

    const body = $("#sheet-body");
    body.querySelectorAll(".sel-art").forEach(cb => cb.addEventListener("change", () => {
      body.querySelectorAll(`.sel-riga[data-a="${cb.dataset.a}"]`).forEach(x => x.checked = cb.checked);
      aggiornaBottoni();
    }));
    body.querySelectorAll(".sel-riga").forEach(cb => cb.addEventListener("change", () => {
      const tutte = [...body.querySelectorAll(`.sel-riga[data-a="${cb.dataset.a}"]`)];
      body.querySelector(`.sel-art[data-a="${cb.dataset.a}"]`).checked = tutte.every(x => x.checked);
      aggiornaBottoni();
    }));

    const scelta = () => ({
      nome: c.nome,
      articoli: c.articoli.map((a, ai) => ({
        descrizione: a.descrizione,
        righe: a.righe.filter((_, ri) => body.querySelector(`.sel-riga[data-a="${ai}"][data-r="${ri}"]`).checked),
      })).filter(a => a.righe.length),
    });

    const box = $("#sheet-actions"); box.textContent = "";
    const ristampa = document.createElement("button");
    ristampa.type = "button"; ristampa.className = "btn btn-primary btn-wide";
    const duplica = document.createElement("button");
    duplica.type = "button"; duplica.className = "btn btn-outline btn-wide"; duplica.textContent = "Duplica e modifica";
    const chiudi = document.createElement("button");
    chiudi.type = "button"; chiudi.className = "btn btn-outline btn-wide"; chiudi.textContent = "Chiudi";
    box.append(ristampa, duplica, chiudi);

    function aggiornaBottoni() {
      const n = totale(scelta());
      const tutto = n === totale(c);
      ristampa.textContent = n ? (tutto ? `Ristampa tutto (${n})` : `Ristampa ${n} ${n === 1 ? "etichetta" : "etichette"}`) : "Nessuna riga scelta";
      ristampa.disabled = n === 0;
    }
    aggiornaBottoni();

    ristampa.addEventListener("click", async () => {
      const sc = scelta(), n = totale(sc);
      if (n > 200 && !confirm(`Stai per ristampare ${n} etichette (più di 200). Confermi?`)) return;
      FF.avviaStampa(sc, 1, n > 200, d.id);
    });
    duplica.addEventListener("click", () => {
      FF.chiudiSheet();
      FF.carica(JSON.parse(JSON.stringify(c)));
      FF.toast("Commessa copiata: modificala e stampa");
    });
    chiudi.addEventListener("click", FF.chiudiSheet);
    FF.apriSheet();
  }

  const totale = c => c.articoli.reduce((s, a) => s + a.righe.reduce((t, r) => t + r.copie, 0), 0);

  document.addEventListener("DOMContentLoaded", () => {
    $("#cerca").addEventListener("input", () => { clearTimeout(tCerca); tCerca = setTimeout(carica, 250); });
    document.querySelectorAll(".filtri button").forEach(b => b.addEventListener("click", () => {
      filtro = b.dataset.stato;
      document.querySelectorAll(".filtri button").forEach(x => {
        x.classList.toggle("is-on", x === b); x.setAttribute("aria-checked", x === b);
      });
      carica();
    }));
    $("#storico-lista").addEventListener("click", e => {
      const it = e.target.closest(".storico-item");
      if (it) apri(+it.dataset.id);
    });
  });

  window.FFStorico = { carica, invalida() { aggiornare = true; } };
})();
