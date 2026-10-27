"""Espansione di una commessa nella sequenza ordinata di etichette."""
from __future__ import annotations

import re
from typing import List, Tuple

from .label.label import SIZES, Etichetta, EtichettaOrdine, impagina_ordine
from .models import Commessa, Impostazioni, VoceStampa

_N_XL = re.compile(r"^(\d+)\s*XL$", re.I)          # 4XL, 5XL…
_X_XL = re.compile(r"^(X{3,})L$", re.I)            # XXXL, XXXXL
_BIMBO = re.compile(r"^(\d+)(?:\s*[-/]\s*(\d+))?\s*(?:A|ANNI|Y)?$", re.I)   # 8-10A, 12A, 6


def chiave_taglia(taglia: str, pos: int) -> Tuple:
    """Ordine dalla più piccola alla più grande:
    taglie bimbo (per età) < XS … 3XL < 4XL, 5XL… < altre personalizzate (ordine di inserimento)."""
    t = taglia.strip().upper()
    if t in SIZES:
        return (1, SIZES.index(t), 0, pos)
    m = _N_XL.match(t)
    if m:
        return (1, len(SIZES) - 1 + int(m.group(1)) - 3, 0, pos)
    m = _X_XL.match(t)
    if m:
        return (1, len(SIZES) - 1 + len(m.group(1)) - 3, 0, pos)
    m = _BIMBO.match(t)
    if m:
        return (0, int(m.group(1)), int(m.group(2) or m.group(1)), pos)
    return (2, 0, 0, pos)


def sequenza(c: Commessa) -> List[VoceStampa]:
    """Articolo per articolo, taglie dalla più piccola alla più grande, copie consecutive.
    Righe con la stessa taglia nello stesso articolo restano separate ma adiacenti."""
    voci: List[VoceStampa] = []
    n = 0
    for ai, art in enumerate(c.articoli):
        righe = sorted(enumerate(art.righe), key=lambda p: chiave_taglia(p[1].taglia, p[0]))
        for _, r in righe:
            for k in range(r.copie):
                n += 1
                voci.append(VoceStampa(indice=n, articolo=ai, descrizione=art.descrizione,
                                       taglia=r.taglia, copia=k + 1, copie=r.copie))
    return voci


def articoli_ordine(c: Commessa) -> List[Tuple[str, Tuple[Tuple[str, int], ...]]]:
    """Articoli con capi, righe nell'ordine delle taglie (stesso ordine della stampa per capo)."""
    out = []
    for art in c.articoli:
        righe = sorted(enumerate(art.righe), key=lambda p: chiave_taglia(p[1].taglia, p[0]))
        righe = tuple((r.taglia, r.copie) for _, r in righe if r.copie > 0)
        if righe:
            out.append((art.descrizione, righe))
    return out


def fogli_ordine(c: Commessa) -> List[list]:
    return impagina_ordine(articoli_ordine(c))


def etichette_ordine(c: Commessa, imp: Impostazioni) -> List[EtichettaOrdine]:
    """Copia per copia (= collo per collo), tutti i fogli del riepilogo."""
    fogli = fogli_ordine(c)
    n = c.copie_ordine
    numera = c.numera_colli and n > 1
    return [EtichettaOrdine(commessa=c.nome, articoli=tuple(f), capi=c.totale, foglio=k + 1, fogli=len(fogli),
                            collo=i + 1 if numera else None, colli=n if numera else None,
                            compensazione=imp.compensazione)
            for i in range(n) for k, f in enumerate(fogli)]


def tutte_le_etichette(c: Commessa, imp: Impostazioni) -> list:
    """Sequenza completa di stampa per la commessa, nella modalità scelta."""
    return etichette_ordine(c, imp) if c.tipo == "ordine" else etichette(c, imp)


def etichette(c: Commessa, imp: Impostazioni, voci: List[VoceStampa] | None = None) -> List[Etichetta]:
    voci = sequenza(c) if voci is None else voci
    tot = len(sequenza(c))
    # senza contatore indice/totale non compaiono: le copie identiche restano uguali
    # (e la stampa le disegna una volta sola)
    return [Etichetta(commessa=c.nome, descrizione=v.descrizione, taglia=v.taglia,
                      indice=v.indice if imp.contatore else None,
                      totale=tot if imp.contatore else None, mostra_commessa=imp.mostra_commessa,
                      contatore=imp.contatore, compensazione=imp.compensazione) for v in voci]
