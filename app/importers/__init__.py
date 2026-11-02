"""Import di file d'ordine. Ogni formato è un `Importer` registrato qui, il primo che
riconosce il file lo legge.

- word.py: la "Scheda di produzione" Fortitude in Word (.docx);
- pdf.py: la stessa scheda in PDF, anche scansionata o fotografata (OCR locale con Tesseract);
- tabella.py: tabelle CSV/Excel generiche, colonne riconosciute dal nome.
"""
from .base import Importer, ImportNonDisponibile, MappaturaColonne, RisultatoImport
from .pdf import ImporterPdf
from .tabella import ImporterTabella
from .word import ImporterWord

REGISTRO: list[Importer] = [ImporterWord(), ImporterPdf(), ImporterTabella()]


def trova_importer(nome_file: str, contenuto: bytes) -> Importer:
    for imp in REGISTRO:
        if imp.riconosce(nome_file, contenuto):
            return imp
    raise ImportNonDisponibile(
        "Formato non supportato: carica la scheda di produzione Word (.docx) o PDF, una foto "
        "(JPG/PNG), un CSV o un Excel (.xlsx).")


__all__ = ["Importer", "ImportNonDisponibile", "MappaturaColonne", "RisultatoImport",
           "REGISTRO", "trova_importer"]
