"""Persistenza SQLite: impostazioni e storico delle commesse stampate."""
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


def registra_stampa(commessa_id: int, stampata: Commessa, da_indice: int) -> int:
    init_db()
    with connessione() as con:
        cur = con.execute("INSERT INTO stampe (commessa_id, data, dati, totale, da_indice, stato) "
                          "VALUES (?, ?, ?, ?, ?, 'in_corso')",
                          (commessa_id, _ora(), stampata.model_dump_json(), stampata.totale, da_indice))
        return cur.lastrowid


def chiudi_stampa(stampa_id: int, stato: str, inviate: int, errore: Optional[str]) -> None:
    with connessione() as con:
        con.execute("UPDATE stampe SET stato = ?, inviate = ?, errore = ? WHERE id = ?",
                    (stato, inviate, errore, stampa_id))


def elenco_commesse(q: str = "", limite: int = 100) -> List[dict]:
    init_db()
    sql = ("SELECT c.id, c.creata, c.nome, c.totale, c.dati, "
           "(SELECT MAX(s.data) FROM stampe s WHERE s.commessa_id = c.id) AS ultima, "
           "(SELECT COUNT(*) FROM stampe s WHERE s.commessa_id = c.id) AS n_stampe, "
           "(SELECT s.stato FROM stampe s WHERE s.commessa_id = c.id ORDER BY s.id DESC LIMIT 1) AS esito "
           "FROM commesse c")
    args: list = []
    parole = [p for p in q.lower().split() if p]
    if parole:
        sql += " WHERE " + " AND ".join("c.testo LIKE ? ESCAPE '\\'" for _ in parole)
        args += ["%" + p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for p in parole]
    sql += " ORDER BY COALESCE(ultima, c.creata) DESC, c.id DESC LIMIT ?"
    args.append(limite)
    with connessione() as con:
        rows = con.execute(sql, args).fetchall()
    out = []
    for r in rows:
        c = Commessa.model_validate_json(r["dati"])
        out.append({"id": r["id"], "nome": r["nome"], "creata": r["creata"], "ultima_stampa": r["ultima"],
                    "totale": r["totale"], "n_stampe": r["n_stampe"], "esito": r["esito"],
                    "articoli": [a.descrizione for a in c.articoli]})
    return out


def leggi_commessa(cid: int) -> Optional[dict]:
    init_db()
    with connessione() as con:
        r = con.execute("SELECT * FROM commesse WHERE id = ?", (cid,)).fetchone()
        if not r:
            return None
        st = con.execute("SELECT * FROM stampe WHERE commessa_id = ? ORDER BY id DESC", (cid,)).fetchall()
    return {"id": r["id"], "creata": r["creata"], "commessa": json.loads(r["dati"]),
            "stampe": [{"id": s["id"], "data": s["data"], "totale": s["totale"], "da_indice": s["da_indice"],
                        "inviate": s["inviate"], "stato": s["stato"], "errore": s["errore"],
                        "commessa": json.loads(s["dati"])} for s in st]}
