"""Persistenza SQLite (impostazioni; lo storico arriva al passo 5)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager

from .models import Impostazioni

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
        con.execute("CREATE TABLE IF NOT EXISTS impostazioni (k TEXT PRIMARY KEY, v TEXT NOT NULL)")


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
