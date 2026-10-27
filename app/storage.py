"""Persistenza SQLite: impostazioni e storico delle commesse (stampate o salvate per dopo).

Una commessa senza stampe è una bozza "da stampare": si può ancora modificare o eliminare.
Dopo la prima stampa resta fissa (si ristampa o si duplica)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager

from datetime import datetime
from typing import List, Optional

from .models import Commessa, Impostazioni

DATA_DIR = os.environ.get("FF_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

_lock = threading.Lock()


def db_path() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, "ff_etichette.db")


@contextmanager
def connessione():
    with _lock:
        con = sqlite3.connect(db_path())
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


def init_db() -> None:
    with connessione() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS impostazioni (k TEXT PRIMARY KEY, v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS commesse (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creata TEXT NOT NULL,
            nome TEXT NOT NULL,
            dati TEXT NOT NULL,            -- Commessa completa (JSON)
            totale INTEGER NOT NULL,
            testo TEXT NOT NULL            -- nome + descrizioni, minuscolo, per la ricerca
        );
        CREATE TABLE IF NOT EXISTS stampe (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commessa_id INTEGER NOT NULL REFERENCES commesse(id),
            data TEXT NOT NULL,
            dati TEXT NOT NULL,            -- righe effettivamente mandate (tutte o una parte)
            totale INTEGER NOT NULL,
            da_indice INTEGER NOT NULL,
            inviate INTEGER NOT NULL DEFAULT 0,
            stato TEXT NOT NULL,
            errore TEXT
        );
        CREATE INDEX IF NOT EXISTS stampe_commessa ON stampe(commessa_id);
        """)


def leggi_impostazioni() -> Impostazioni:
    init_db()
    with connessione() as con:
        row = con.execute("SELECT v FROM impostazioni WHERE k = 'generali'").fetchone()
    return Impostazioni(**json.loads(row["v"])) if row else Impostazioni()


def salva_impostazioni(imp: Impostazioni) -> Impostazioni:
    init_db()
    with connessione() as con:
        con.execute("INSERT INTO impostazioni (k, v) VALUES ('generali', ?) "
                    "ON CONFLICT(k) DO UPDATE SET v = excluded.v", (imp.model_dump_json(),))
    return imp


# ---------------------------------------------------------------- storico
def _ora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _testo(c: Commessa) -> str:
    return " ".join([c.nome] + [a.descrizione for a in c.articoli]).lower()


def salva_commessa(c: Commessa) -> int:
    init_db()
    with connessione() as con:
        cur = con.execute("INSERT INTO commesse (creata, nome, dati, totale, testo) VALUES (?, ?, ?, ?, ?)",
                          (_ora(), c.nome, c.model_dump_json(), c.totale, _testo(c)))
        return cur.lastrowid


def _ha_stampe(con, cid: int) -> bool:
    return con.execute("SELECT 1 FROM stampe WHERE commessa_id = ? LIMIT 1", (cid,)).fetchone() is not None


def aggiorna_bozza(cid: int, c: Commessa) -> bool:
    """Sovrascrive una commessa salvata per dopo. False se non esiste o è già stata stampata."""
    init_db()
    with connessione() as con:
        if not con.execute("SELECT 1 FROM commesse WHERE id = ?", (cid,)).fetchone() or _ha_stampe(con, cid):
            return False
        con.execute("UPDATE commesse SET creata = ?, nome = ?, dati = ?, totale = ?, testo = ? WHERE id = ?",
                    (_ora(), c.nome, c.model_dump_json(), c.totale, _testo(c), cid))
        return True


def elimina_bozza(cid: int) -> bool:
    """Elimina una commessa salvata per dopo. False se non esiste o è già stata stampata."""
    init_db()
    with connessione() as con:
        if _ha_stampe(con, cid):
            return False
        return con.execute("DELETE FROM commesse WHERE id = ?", (cid,)).rowcount > 0


def e_bozza(cid: int) -> bool:
    init_db()
    with connessione() as con:
        return (con.execute("SELECT 1 FROM commesse WHERE id = ?", (cid,)).fetchone() is not None
                and not _ha_stampe(con, cid))


def registra_stampa(commessa_id: int, stampata: Commessa, da_indice: int, totale: Optional[int] = None) -> int:
    """`totale`: etichette dell'intero job (default: i capi, che in modalità "capo" coincidono)."""
    init_db()
    with connessione() as con:
        cur = con.execute("INSERT INTO stampe (commessa_id, data, dati, totale, da_indice, stato) "
                          "VALUES (?, ?, ?, ?, ?, 'in_corso')",
                          (commessa_id, _ora(), stampata.model_dump_json(),
                           stampata.totale if totale is None else totale, da_indice))
        return cur.lastrowid


def chiudi_stampa(stampa_id: int, stato: str, inviate: int, errore: Optional[str]) -> None:
    with connessione() as con:
        con.execute("UPDATE stampe SET stato = ?, inviate = ?, errore = ? WHERE id = ?",
                    (stato, inviate, errore, stampa_id))


def elenco_commesse(q: str = "", limite: int = 100, stato: str = "") -> List[dict]:
    """`stato`: "" tutte, "bozze" solo quelle salvate per dopo, "stampate" solo quelle stampate."""
    init_db()
    sql = ("SELECT c.id, c.creata, c.nome, c.totale, c.dati, "
           "(SELECT MAX(s.data) FROM stampe s WHERE s.commessa_id = c.id) AS ultima, "
           "(SELECT COUNT(*) FROM stampe s WHERE s.commessa_id = c.id) AS n_stampe, "
           "(SELECT s.stato FROM stampe s WHERE s.commessa_id = c.id ORDER BY s.id DESC LIMIT 1) AS esito "
           "FROM commesse c")
    args: list = []
    cond = []
    parole = [p for p in q.lower().split() if p]
    if parole:
        cond += ["c.testo LIKE ? ESCAPE '\\'" for _ in parole]
        args += ["%" + p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for p in parole]
    if stato in ("bozze", "stampate"):
        cond.append(("NOT " if stato == "bozze" else "") + "EXISTS (SELECT 1 FROM stampe s WHERE s.commessa_id = c.id)")
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY COALESCE(ultima, c.creata) DESC, c.id DESC LIMIT ?"
    args.append(limite)
    with connessione() as con:
        rows = con.execute(sql, args).fetchall()
    out = []
    for r in rows:
        c = Commessa.model_validate_json(r["dati"])
        out.append({"id": r["id"], "nome": r["nome"], "creata": r["creata"], "ultima_stampa": r["ultima"],
                    "totale": r["totale"], "n_stampe": r["n_stampe"], "esito": r["esito"],
                    "bozza": r["n_stampe"] == 0, "tipo": c.tipo,
                    "articoli": [a.descrizione for a in c.articoli]})
    return out


def leggi_commessa(cid: int) -> Optional[dict]:
    init_db()
    with connessione() as con:
        r = con.execute("SELECT * FROM commesse WHERE id = ?", (cid,)).fetchone()
        if not r:
            return None
        st = con.execute("SELECT * FROM stampe WHERE commessa_id = ? ORDER BY id DESC", (cid,)).fetchall()
    return {"id": r["id"], "creata": r["creata"], "commessa": json.loads(r["dati"]), "bozza": not st,
            "stampe": [{"id": s["id"], "data": s["data"], "totale": s["totale"], "da_indice": s["da_indice"],
                        "inviate": s["inviate"], "stato": s["stato"], "errore": s["errore"],
                        "commessa": json.loads(s["dati"])} for s in st]}
