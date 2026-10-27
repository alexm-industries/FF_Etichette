"""Modelli dati condivisi da API, stampa, storico e importer."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

MAX_COPIE_RIGA = 9999
MAX_COPIE_ORDINE = 99


class RigaTaglia(BaseModel):
    taglia: str = Field(min_length=1, max_length=40)
    copie: int = Field(ge=0, le=MAX_COPIE_RIGA)

    @field_validator("taglia")
    @classmethod
    def _pulisci(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("taglia vuota")
        return v


class Articolo(BaseModel):
    descrizione: str = Field(default="", max_length=300)
    righe: List[RigaTaglia] = Field(default_factory=list)

    @property
    def totale(self) -> int:
        return sum(r.copie for r in self.righe)


class Commessa(BaseModel):
    nome: str = Field(default="", max_length=200)
    articoli: List[Articolo] = Field(default_factory=list)
    # "capo": un'etichetta per busta (le copie di una riga sono i capi = le etichette);
    # "ordine": etichetta di riepilogo per scatola/busta dell'intero ordine (le copie sono i capi)
    tipo: Literal["capo", "ordine"] = "capo"
    copie_ordine: int = Field(default=1, ge=1, le=MAX_COPIE_ORDINE)   # solo "ordine": quante etichette riepilogo
    numera_colli: bool = False                                         # solo "ordine": "COLLO 1/3" in testata

    @property
    def totale(self) -> int:
        """Capi della commessa (in modalità "capo" coincide con le etichette)."""
        return sum(a.totale for a in self.articoli)


class VoceStampa(BaseModel):
    """Una etichetta nella sequenza di stampa."""
    indice: int                      # 1-based nella commessa
    articolo: int                    # indice articolo (0-based)
    descrizione: str
    taglia: str
    copia: int                       # 1..copie della riga
    copie: int


class Impostazioni(BaseModel):
    ip_stampante: str = ""
    modello: str = "QL-810W"
    etichetta: str = "62x100"
    contatore: bool = False
    mostra_commessa: bool = True
    compensazione: float = Field(default=0.25, ge=0, le=0.45)   # scelta con la prova di stampa; vedi label.COMPENSAZIONE_DEFAULT
    pin: Optional[str] = None
