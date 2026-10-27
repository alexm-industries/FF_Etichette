"""Import di file d'ordine. Ogni formato è un `Importer` registrato qui, il primo che
riconosce il file lo legge.

- word.py: la "Scheda di produzione" Fortitude in Word (.docx);
- tabella.py: tabelle CSV/Excel generiche, colonne riconosciute dal nome.
"""
from .base import Importer, ImportNonDisponibile, MappaturaColonne, RisultatoImport
from .tabella import ImporterTabella
from .word import ImporterWord

REGISTRO: list[Importer] = [ImporterWord(), ImporterTabella()]


def trova_importer(nome_file: str, contenuto: bytes) -> Importer:
    for imp in REGISTRO:
        if imp.riconosce(nome_file, contenuto):
            return imp
    raise ImportNonDisponibile(
        "Formato non supportato: carica la scheda di produzione Word (.docx), un CSV o un Excel (.xlsx).")


__all__ = ["Importer", "ImportNonDisponibile", "MappaturaColonne", "RisultatoImport",
           "REGISTRO", "trova_importer"]
