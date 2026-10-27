"""Import della "Scheda di produzione" Fortitude in Word (.docx).

Struttura attesa (vedi la scheda d'esempio):
- tabella in testa con la cella "Cliente" -> nome commessa;
- per ogni articolo un paragrafo "Articolo N - X pz", poi:
  - una tabella chiave/valore (anche annidata) con "Articolo", "Marca e codice", "Colore capo";
  - la tabella "Quantità per taglia": intestazione con le taglie (+ "Totale"), sotto le quantità.
La descrizione è: articolo + colore (minuscolo) + codice, se presente.
Se le quantità non tornano con "Totale" o con gli "X pz" del titolo, l'import lo segnala.
Letto con la libreria standard (zip + XML), senza dipendenze.
"""
from __future__ import annotations

import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from ..models import Articolo, Commessa, RigaTaglia
from .base import Importer, ImportNonDisponibile, MappaturaColonne, RisultatoImport
from .tabella import _norm, _quantita, _taglia_da_intestazione

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_XML = 20 * 1024 * 1024
_TITOLO = re.compile(r"^\s*articolo\s*(\d+)\b(?:.*?(\d+)\s*(?:pz|pezzi|capi)\b)?", re.I)

K_CLIENTE = ["cliente", "commessa"]
K_ARTICOLO = ["articolo", "descrizione", "capo", "prodotto"]
K_COLORE = ["colore capo", "colore"]
K_CODICE = ["marca e codice", "codice", "codice articolo"]


def _testo(el) -> str:
    """Testo di un paragrafo o di una cella (paragrafi uniti da spazio), senza tabelle annidate."""
    parti = []
    for p in el.iter(W + "p"):
        parti.append("".join(t.text or "" for t in p.iter(W + "t")))
    return " ".join(" ".join(parti).split())


def _celle(tbl) -> List[List[ET.Element]]:
    return [tr.findall(W + "tc") for tr in tbl.findall(W + "tr")]


def _cella_testo(tc) -> str:
    """Testo della cella escluse le tabelle annidate."""
    parti = []
    for ch in tc:
        if ch.tag == W + "p":
            parti.append(_testo(ch))
    return " ".join(" ".join(parti).split())


def _chiavi_valori(tbl) -> Dict[str, str]:
    """Coppie etichetta/valore di una tabella (anche su 4 colonne: chiave|valore|chiave|valore),
    comprese quelle delle tabelle annidate."""
    out: Dict[str, str] = {}
    for riga in _celle(tbl):
        testi = [_cella_testo(tc) for tc in riga]
        for k in range(0, len(testi) - 1, 2):
            if testi[k]:
                out.setdefault(_norm(testi[k]), testi[k + 1])
        for tc in riga:
            for sub in tc.findall(W + "tbl"):
                for k, v in _chiavi_valori(sub).items():
                    out.setdefault(k, v)
    return out


def _primo(kv: Dict[str, str], chiavi: List[str]) -> str:
    for k in chiavi:
        if kv.get(k):
            return kv[k]
    return ""


def _tabella_taglie(tbl) -> Optional[tuple]:
    """(coppie taglia/quantità, totale dichiarato, avvisi) se è una tabella "Quantità per taglia"."""
    righe = [[_cella_testo(tc) for tc in r] for r in _celle(tbl)]
    if len(righe) < 2:
        return None
    intest = righe[0]
    taglie = [(k, t) for k, h in enumerate(intest) if (t := _taglia_da_intestazione(h))]
    if len(taglie) < 2:
        return None
    k_tot = next((k for k, h in enumerate(intest) if _norm(h) in ("totale", "tot")), None)
    capi: Dict[str, int] = {}
    avvisi, totale = [], None
    for r in righe[1:]:
        for k, t in taglie:
            q = _quantita(r[k] if k < len(r) else None)
            if q is None:
                avvisi.append(f"quantità non valida nella taglia {t} ({r[k]!r}), ignorata")
            elif q:
                capi[t] = capi.get(t, 0) + q
        if k_tot is not None and k_tot < len(r):
            t = _quantita(r[k_tot])
            if t:
                totale = (totale or 0) + t
    return capi, totale, avvisi


class ImporterWord(Importer):
    nome = "Scheda di produzione (Word)"

    def riconosce(self, nome_file: str, contenuto: bytes) -> bool:
        return nome_file.lower().endswith((".docx", ".doc"))

    def colonne(self, contenuto: bytes) -> List[str]:
        return []

    def _corpo(self, nome_file: str, contenuto: bytes):
        if nome_file.lower().endswith(".doc"):
            raise ImportNonDisponibile("I file .doc (Word 97-2003) non sono supportati: "
                                       "in Word usa File › Salva con nome › Documento Word (.docx).")
        try:
            with zipfile.ZipFile(io.BytesIO(contenuto)) as z:
                info = z.getinfo("word/document.xml")
                if info.file_size > MAX_XML:
                    raise ImportNonDisponibile("Il documento Word è troppo grande.")
                xml = z.read(info)
        except (zipfile.BadZipFile, KeyError):
            raise ImportNonDisponibile("Il file Word non si apre: è danneggiato o protetto da password?")
        try:
            return ET.fromstring(xml).find(W + "body")
        except ET.ParseError:
            raise ImportNonDisponibile("Il file Word non si legge: contenuto non valido.")

    def importa(self, contenuto: bytes, mappatura: Optional[MappaturaColonne] = None,
                nome_file: str = "ordine.docx") -> RisultatoImport:
        body = self._corpo(nome_file, contenuto)
        nome = ""
        avvisi: List[str] = []
        articoli: List[dict] = []
        cur: Optional[dict] = None          # articolo in costruzione

        def nuovo(n_titolo=None, pz=None):
            a = {"n": n_titolo or len(articoli) + 1, "pz": pz, "kv": {}, "capi": None, "tot": None}
            articoli.append(a)
            return a

        for el in body:
            if el.tag == W + "p":
                m = _TITOLO.match(_testo(el))
                if m:
                    cur = nuovo(int(m.group(1)), int(m.group(2)) if m.group(2) else None)
            elif el.tag == W + "tbl":
                tt = _tabella_taglie(el)
                if tt:
                    if cur is None or cur["capi"] is not None:
                        cur = nuovo()          # tabella taglie senza titolo "Articolo N"
                    cur["capi"], cur["tot"] = tt[0], tt[1]
                    avvisi += [f"Articolo {cur['n']}: {a}" for a in tt[2]]
                    continue
                kv = _chiavi_valori(el)
                if not nome:
                    nome = _primo(kv, K_CLIENTE)
                if cur is not None and cur["capi"] is None and _primo(kv, K_ARTICOLO):
                    for k, v in kv.items():
                        cur["kv"].setdefault(k, v)

        arts = []
        for a in articoli:
            n = a["n"]
            if not a["capi"]:
                avvisi.append(f"Articolo {n}: nessuna quantità per taglia, saltato.")
                continue
            somma = sum(a["capi"].values())
            if a["tot"] is not None and a["tot"] != somma:
                avvisi.append(f"Articolo {n}: le taglie sommano {somma} capi ma il Totale della tabella è {a['tot']}.")
            if a["pz"] is not None and a["pz"] != somma:
                avvisi.append(f"Articolo {n}: le taglie sommano {somma} capi ma il titolo dice {a['pz']} pz.")
            art = _primo(a["kv"], K_ARTICOLO)
            colore = _primo(a["kv"], K_COLORE)
            codice = _primo(a["kv"], K_CODICE)
            if not art:
                avvisi.append(f"Articolo {n}: descrizione non trovata.")
            parti = [art, colore.lower() if colore else "", codice]
            descr = " ".join(p for p in parti if p and p != "-")
            arts.append(Articolo(descrizione=descr[:300],
                                 righe=[RigaTaglia(taglia=t[:40], copie=min(q, 9999)) for t, q in a["capi"].items()]))

        if not arts:
            raise ImportNonDisponibile("Nel documento non trovo la tabella «Quantità per taglia» "
                                       "(una riga con le taglie XS, S, M… e sotto le quantità).")
        if not nome:
            nome = os.path.splitext(os.path.basename(nome_file))[0].replace("_", " ").strip()
            avvisi.append("Cliente non trovato nel documento: come commessa uso il nome del file.")
        return RisultatoImport(commessa=Commessa(nome=nome[:200], articoli=arts), avvisi=avvisi)
