"""Import della "Conferma d'ordine" in PDF (es. OFF251): tabella Codice | Descrizione | Q.tà |
Prezzo | Importo | IVA, anche su più pagine ("Continua pagina seguente").

- commessa = la prima riga sotto "Cliente" (il destinatario della conferma);
- una voce per ogni riga con codice o quantità; le righe sotto senza codice continuano la
  descrizione, anche alla pagina dopo;
- descrizione sull'etichetta = la prima frase della descrizione ("T-shirt Color Block 1 - nera");
- taglie dal testo dopo "Taglie:", es. "M 1 - L 1 - XL 1". Una nota tra parentesi dopo la
  taglia ("M 1 (donna)") fa un articolo a parte con la nota nella descrizione;
- se le taglie non sommano alla Q.tà, o nelle taglie c'è altro testo ("+ 3 pz aggiuntivi"),
  l'import lo segnala.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..models import Articolo, RigaTaglia
from .pdf import Parola, Riga, _taglia, righe
from .tabella import _norm, _quantita

_QTA = ("q ta", "qta", "qt", "qty", "quantita")
_TAGLIE = re.compile(r"\btaglie?\s*:", re.I)
_COPPIA = re.compile(r"([A-Za-z0-9][A-Za-z0-9/\-]*)\s+(\d{1,4})\b(?:\s*\(([^)]*)\))?")
_FINE = ("continua pagina", "descrizione iva", "imponibile", "totale")


def _intestazione(r: Riga) -> Optional[Dict[str, Parola]]:
    """Le parole "Codice", "Descrizione" e "Q.tà" se la riga è l'intestazione della tabella."""
    col: Dict[str, Parola] = {}
    for p in r.parole:
        n = _norm(p.testo)
        if n == "codice":
            col.setdefault("codice", p)
        elif n == "descrizione":
            col.setdefault("descrizione", p)
        elif n in _QTA:
            col.setdefault("qta", p)
    if "descrizione" in col and "qta" in col and col["descrizione"].x1 < col["qta"].x0:
        return col
    return None


def _cliente(rr: List[Riga]) -> str:
    """Prima riga sotto l'etichetta "Cliente" (da sola nella riga, non "Cod. Cliente")."""
    for i, r in enumerate(rr):
        if len(r.parole) == 1 and _norm(r.parole[0].testo) == "cliente":
            et = r.parole[0]
            for s in rr[i + 1:i + 3]:
                if s.yc - r.yc > 4 * r.h:
                    break
                testo = " ".join(p.testo for p in s.parole if et.x0 - 3 <= p.x0 <= et.x0 + 250)
                if testo:
                    return testo
    return ""


def _voci(pagine: List[List[Parola]]) -> Optional[Tuple[str, List[dict]]]:
    """(cliente, [{codice, qta, testo}]) oppure None se non c'è la tabella della conferma."""
    nome, voci, trovata = "", [], False
    for parole in pagine:
        rr = righe(parole)
        nome = nome or _cliente(rr)
        col, i = None, 0
        while i < len(rr) and not col:
            col = _intestazione(rr[i])
            i += 1
        if not col:
            continue
        trovata = True
        d, q = col["descrizione"], col["qta"]
        sinistra = (col["codice"].x0 if "codice" in col else d.x0) - 12
        for r in rr[i:]:
            if any(p.x1 < sinistra for p in r.parole) or _norm(r.testo).startswith(_FINE):
                break                                    # piede della pagina o riepilogo IVA
            codice = " ".join(p.testo for p in r.parole if p.x1 <= d.x0 - 1)
            testo = " ".join(p.testo for p in r.parole if d.x0 - 3 <= p.x0 and p.x1 < q.x0 - 4)
            qta = next((_quantita(p.testo) for p in r.parole
                        if q.x0 - 15 <= p.xc <= q.x1 + 15 and _quantita(p.testo)), None)
            if codice or qta is not None:
                voci.append({"codice": codice, "qta": qta, "testo": testo})
            elif voci and testo:
                voci[-1]["testo"] += " " + testo
    return (nome, voci) if trovata else None


def _taglie(testo: str) -> Tuple[Dict[str, Dict[str, int]], str]:
    """{nota: {taglia: capi}} dal testo dopo "Taglie:" e il testo avanzato (non letto)."""
    gruppi: Dict[str, Dict[str, int]] = {}
    avanzo, da = [], 0
    for m in _COPPIA.finditer(testo):
        t = _taglia(m.group(1))
        if not t:
            continue
        nota = " ".join((m.group(3) or "").split())
        capi = gruppi.setdefault(nota, {})
        capi[t] = capi.get(t, 0) + int(m.group(2))
        avanzo.append(testo[da:m.start()])
        da = m.end()
    avanzo.append(testo[da:])
    resto = " ".join(" ".join(avanzo).split()).strip(" -–,;+.")
    return gruppi, resto


def interpreta_conferma(pagine: List[List[Parola]]) -> Optional[Tuple[str, List[Articolo], List[str]]]:
    letto = _voci(pagine)
    if letto is None:
        return None
    nome, voci = letto
    arts: List[Articolo] = []
    avvisi: List[str] = []
    for v in voci:
        m = _TAGLIE.search(v["testo"])
        corpo = v["testo"][:m.start()] if m else v["testo"]
        frase = re.match(r"\s*(.+?)\.(?:\s|$)", corpo)
        descr = (frase.group(1) if frase else corpo).strip()[:280] or v["codice"]
        if not m:
            avvisi.append(f"{descr}: taglie non indicate, saltato.")
            continue
        gruppi, resto = _taglie(v["testo"][m.end():])
        if not gruppi:
            avvisi.append(f"{descr}: taglie non lette («{resto}»), saltato.")
            continue
        somma = sum(sum(c.values()) for c in gruppi.values())
        if v["qta"] is not None and v["qta"] != somma:
            avvisi.append(f"{descr}: le taglie sommano {somma} capi ma la Q.tà è {v['qta']}.")
        if resto:
            avvisi.append(f"{descr}: nelle taglie c'è anche «{resto}», non importato.")
        for nota in sorted(gruppi, key=bool):          # prima le taglie senza nota
            arts.append(Articolo(descrizione=f"{descr} ({nota})" if nota else descr,
                                 righe=[RigaTaglia(taglia=t[:40], copie=min(q, 9999))
                                        for t, q in gruppi[nota].items()]))
    return nome, arts, avvisi
