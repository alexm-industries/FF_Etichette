"""Import di file d'ordine. Ogni formato è un `Importer` registrato qui.

Il formato reale del file d'ordine Fortitude non è ancora noto: per ora c'è un importer
generico per tabelle CSV/Excel che riconosce le colonne dal nome (vedi tabella.py).
Quando arriva un file d'esempio, un importer specifico va registrato prima di questo.
"""
from .base import Importer, ImportNonDisponibile, MappaturaColonne, RisultatoImport
from .tabella import ImporterTabella

REGISTRO: list[Importer] = [ImporterTabella()]


def trova_importer(nome_file: str, contenuto: bytes) -> Importer:
    for imp in REGISTRO:
        if imp.riconosce(nome_file, contenuto):
            return imp
    raise ImportNonDisponibile(
        "Formato non supportato: carica un file CSV o Excel (.xlsx).")


__all__ = ["Importer", "ImportNonDisponibile", "MappaturaColonne", "RisultatoImport",
           "REGISTRO", "trova_importer"]
