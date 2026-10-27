"""Interfaccia comune degli importer (fase 2)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..models import Commessa


class ImportNonDisponibile(Exception):
    pass


class MappaturaColonne(BaseModel):
    """Quale colonna del file corrisponde a quale campo. Scelta dall'utente nella
    schermata di mappatura e ricordata per i file successivi dello stesso tipo."""
    commessa: Optional[str] = None
    descrizione: Optional[str] = None
    taglia: Optional[str] = None
    copie: Optional[str] = None
    # formato "a colonne": una colonna per taglia (es. S, M, L) con le quantità
    colonne_taglia: Dict[str, str] = Field(default_factory=dict)


class RisultatoImport(BaseModel):
    commessa: Commessa
    colonne: List[str] = Field(default_factory=list)       # intestazioni trovate nel file
    mappatura: MappaturaColonne = Field(default_factory=MappaturaColonne)
    avvisi: List[str] = Field(default_factory=list)        # righe scartate, valori dubbi


class Importer(ABC):
    nome: str = ""

    @abstractmethod
    def riconosce(self, nome_file: str, contenuto: bytes) -> bool: ...

    @abstractmethod
    def colonne(self, contenuto: bytes) -> List[str]: ...

    @abstractmethod
    def importa(self, contenuto: bytes, mappatura: Optional[MappaturaColonne] = None) -> RisultatoImport:
        """Estrae la commessa precompilata; l'utente la controlla prima di stampare."""
