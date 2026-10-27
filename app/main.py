"""Server FF Etichette: API + frontend statico, solo rete locale."""
from __future__ import annotations

import hmac
import io
import ipaddress
import os
import re
import socket
from functools import lru_cache
from typing import Optional

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import storage
from .importers import ImportNonDisponibile, trova_importer
from .jobs import etichette, sequenza
from .label.label import png_bytes, render_label, render_pdf
from .models import Commessa, Impostazioni

PORTA = int(os.environ.get("FF_PORT", "8000"))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
LIMITE_CONFERMA = 200

app = FastAPI(title="FF Etichette", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------- sicurezza: solo LAN + PIN opzionale
def _ip_locale(host: Optional[str]) -> bool:
    if not host:
        return False
    if host == "testclient":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


PUBBLICI = {"/api/accesso", "/manifest.webmanifest", "/sw.js"}


@app.middleware("http")
async def solo_rete_locale(request: Request, call_next):
    if not _ip_locale(request.client.host if request.client else None):
        return JSONResponse({"detail": "Accesso consentito solo dalla rete locale."}, status_code=403)
    path = request.url.path
    if path.startswith("/api/") and path not in PUBBLICI:
        pin = storage.leggi_impostazioni().pin
        if pin and not hmac.compare_digest(request.cookies.get("ff_pin", ""), pin):
            return JSONResponse({"detail": "PIN richiesto."}, status_code=401)
    return await call_next(request)


class Accesso(BaseModel):
    pin: str


@app.post("/api/accesso")
def accesso(a: Accesso, response: Response):
    pin = storage.leggi_impostazioni().pin
    if pin and not hmac.compare_digest(a.pin, pin):
        raise HTTPException(401, "PIN errato.")
    response.set_cookie("ff_pin", a.pin, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 365)
    return {"ok": True}


# ---------------------------------------------------------------- anteprima, riepilogo, PDF
@lru_cache(maxsize=256)
def _anteprima(commessa, articolo, taglia, i, n, mostra_commessa, contatore) -> bytes:
    return png_bytes(render_label(commessa, articolo, taglia or None, i, n, mostra_commessa, contatore))


@app.get("/api/anteprima.png")
def anteprima(commessa: str = "", articolo: str = "", taglia: str = "",
              i: Optional[int] = Query(None, ge=1), n: Optional[int] = Query(None, ge=1)):
    imp = storage.leggi_impostazioni()
    png = _anteprima(commessa[:200], articolo[:300], taglia[:40], i, n,
                     imp.mostra_commessa, imp.contatore)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/riepilogo")
def riepilogo(c: Commessa):
    voci = sequenza(c)
    return {
        "totale": len(voci),
        "richiede_conferma_extra": len(voci) > LIMITE_CONFERMA,
        "articoli": [{"descrizione": a.descrizione, "totale": a.totale} for a in c.articoli],
        # righe raggruppate nell'ordine di stampa: articolo / taglia / copie / da-a
        "righe": _raggruppa(voci),
    }


def _raggruppa(voci):
    out = []
    for v in voci:
        if out and out[-1]["articolo"] == v.articolo and out[-1]["taglia"] == v.taglia and v.copia > 1:
            out[-1]["copie"] += 1; out[-1]["a"] = v.indice
        else:
            out.append({"articolo": v.articolo, "descrizione": v.descrizione, "taglia": v.taglia,
                        "copie": 1, "da": v.indice, "a": v.indice})
    return out


def _nome_file(c: Commessa) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", c.nome.strip()).strip("_") or "commessa"
    return f"etichette_{base[:60]}.pdf"


@app.post("/api/pdf")
def pdf(c: Commessa):
    if c.totale == 0:
        raise HTTPException(400, "Nessuna etichetta da generare.")
    data = render_pdf(etichette(c, storage.leggi_impostazioni()))
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_nome_file(c)}"'})


# ---------------------------------------------------------------- impostazioni e info
@app.get("/api/impostazioni")
def get_impostazioni():
    d = storage.leggi_impostazioni().model_dump()
    d["pin_attivo"] = bool(d.pop("pin"))
    return d


class ModificaImpostazioni(BaseModel):
    ip_stampante: Optional[str] = None
    modello: Optional[str] = None
    etichetta: Optional[str] = None
    contatore: Optional[bool] = None
    mostra_commessa: Optional[bool] = None
    pin: Optional[str] = None        # "" = toglie il PIN


@app.put("/api/impostazioni")
def put_impostazioni(m: ModificaImpostazioni, response: Response):
    imp = storage.leggi_impostazioni()
    dati = m.model_dump(exclude_unset=True)
    if "pin" in dati:
        pin = (dati["pin"] or "").strip()
        if pin and not re.fullmatch(r"\d{4,8}", pin):
            raise HTTPException(400, "Il PIN deve avere da 4 a 8 cifre.")
        dati["pin"] = pin or None
        if pin:
            response.set_cookie("ff_pin", pin, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 365)
    if dati.get("ip_stampante"):
        dati["ip_stampante"] = dati["ip_stampante"].strip()
    storage.salva_impostazioni(imp.model_copy(update=dati))
    _anteprima.cache_clear()
    return get_impostazioni()


def indirizzo_lan() -> str:
    """IP della scheda di rete usata per uscire (nessun pacchetto viene inviato)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@app.get("/api/info")
def info():
    url = f"http://{indirizzo_lan()}:{PORTA}/"
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, border=1)
    buf = io.BytesIO(); img.save(buf)
    return {"url": url, "qr_svg": buf.getvalue().decode()}


# ---------------------------------------------------------------- fase 2: import (predisposto)
@app.post("/api/import")
async def importa(file: UploadFile = File(...)):
    contenuto = await file.read()
    try:
        imp = trova_importer(file.filename or "", contenuto)
    except ImportNonDisponibile as e:
        raise HTTPException(501, str(e))
    return imp.importa(contenuto).model_dump()


if os.path.isdir(STATIC):
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
