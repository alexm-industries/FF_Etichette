"""Fase 2: import di file d'ordine. Ogni formato è un `Importer` registrato qui.

Il formato reale del file d'ordine Fortitude non è ancora noto: nessun parser concreto
è registrato finché non arriva un file d'esempio.
"""
from .base import Importer, ImportNonDisponibile, MappaturaColonne, RisultatoImport

REGISTRO: list[Importer] = []


def trova_importer(nome_file: str, contenuto: bytes) -> Importer:
    for imp in REGISTRO:
        if imp.riconosce(nome_file, contenuto):
            return imp
    raise ImportNonDisponibile(
        "Import da file non ancora disponibile: serve un file d'ordine d'esempio per definire il formato.")


__all__ = ["Importer", "ImportNonDisponibile", "MappaturaColonne", "RisultatoImport",
           "REGISTRO", "trova_importer"]
