/* Storico: cerca, apri, duplica, ristampa tutto o solo alcune righe. */
"use strict";
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  let tCerca, aggiornare = true;

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
    try { lista = await (await FF.api("/api/storico?q=" + encodeURIComponent(q))).json(); }
    catch (e) { box.innerHTML = `<p class="err">${FF.esc(e.message)}</p>`; return; }
    aggiornare = false;
    if (!lista.length) {
      box.innerHTML = `<p class="muted">${q ? "Nessuna commessa trovata." : "Nessuna commessa stampata finora."}</p>`;
      return;
    }
    box.innerHTML = lista.map(c => `
      <button class="storico-item" type="button" data-id="${c.id}">
        <span class="si-top"><strong>${FF.esc(c.nome || "Senza nome")}</strong><span class="si-n">${c.totale}</span></span>
        <span class="si-art">${FF.esc(c.articoli.filter(Boolean).join(" · ") || "—")}</span>
        <span class="si-meta">${dataIt(c.ultima_stampa || c.creata)}${c.n_stampe > 1 ? ` · ${c.n_stampe} stampe` : ""}
          ${c.esito && c.esito !== "completato" ? `<span class="si-warn">${ESITO[c.esito] || c.esito}</span>` : ""}</span>
      </button>`).join("");
  }

  async function apri(id) {
    let d;
    try { d = await (await FF.api("/api/storico/" + id)).json(); } catch (e) { return FF.toast(e.message, true); }
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
      FF.carica(JSON.parse(JSON.stringify({ nome: c.nome, articoli: c.articoli })));
      FF.toast("Commessa copiata: modificala e stampa");
    });
    chiudi.addEventListener("click", FF.chiudiSheet);
    FF.apriSheet();
  }

  const totale = c => c.articoli.reduce((s, a) => s + a.righe.reduce((t, r) => t + r.copie, 0), 0);

  document.addEventListener("DOMContentLoaded", () => {
    $("#cerca").addEventListener("input", () => { clearTimeout(tCerca); tCerca = setTimeout(carica, 250); });
    $("#storico-lista").addEventListener("click", e => {
      const it = e.target.closest(".storico-item");
      if (it) apri(+it.dataset.id);
    });
  });

  window.FFStorico = { carica, invalida() { aggiornare = true; } };
})();
