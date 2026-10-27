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

from . import printer, storage
from .importers import ImportNonDisponibile, trova_importer
from .jobs import articoli_ordine, fogli_ordine, sequenza, tutte_le_etichette
from .label.label import EtichettaOrdine, png_bytes, render_etichetta, render_label, render_pdf
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


PUBBLICI = {"/api/accesso"}


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
def _anteprima(commessa, articolo, taglia, i, n, mostra_commessa, contatore, compensazione) -> bytes:
    return png_bytes(render_label(commessa, articolo, taglia or None, i, n, mostra_commessa, contatore,
                                  compensazione=compensazione))


@app.get("/api/anteprima.png")
def anteprima(commessa: str = "", articolo: str = "", taglia: str = "",
              i: Optional[int] = Query(None, ge=1), n: Optional[int] = Query(None, ge=1)):
    imp = storage.leggi_impostazioni()
    png = _anteprima(commessa[:200], articolo[:300], taglia[:40], i, n,
                     imp.mostra_commessa, imp.contatore, imp.compensazione)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@lru_cache(maxsize=64)
def _anteprima_ordine(dati: str, foglio: int, compensazione: float) -> tuple:
    c = Commessa.model_validate_json(dati)
    fogli = fogli_ordine(c)
    k = min(max(foglio, 1), max(len(fogli), 1))
    e = EtichettaOrdine(commessa=c.nome, articoli=tuple(fogli[k - 1]) if fogli else (), capi=c.totale,
                        foglio=k, fogli=max(len(fogli), 1),
                        collo=1 if c.numera_colli and c.copie_ordine > 1 else None,
                        colli=c.copie_ordine if c.numera_colli and c.copie_ordine > 1 else None,
                        compensazione=compensazione)
    return png_bytes(render_etichetta(e)), max(len(fogli), 1)


@app.post("/api/anteprima-ordine.png")
def anteprima_ordine(c: Commessa, foglio: int = Query(1, ge=1)):
    """Anteprima dell'etichetta riepilogo (un foglio). Nelle intestazioni: fogli e etichette totali."""
    imp = storage.leggi_impostazioni()
    png, n = _anteprima_ordine(c.model_dump_json(), foglio, imp.compensazione)
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "no-store", "X-Fogli": str(n),
                             "X-Etichette": str(n * c.copie_ordine if c.totale else 0)})


@app.post("/api/riepilogo")
def riepilogo(c: Commessa):
    if c.tipo == "ordine":
        return _riepilogo_ordine(c)
    voci = sequenza(c)
    return {
        "tipo": "capo",
        "totale": len(voci),
        "richiede_conferma_extra": len(voci) > LIMITE_CONFERMA,
        "articoli": [{"descrizione": a.descrizione, "totale": a.totale} for a in c.articoli],
        # righe raggruppate nell'ordine di stampa: articolo / taglia / copie / da-a
        "righe": _raggruppa(voci),
    }


def _riepilogo_ordine(c: Commessa) -> dict:
    arts = articoli_ordine(c)
    fogli = len(fogli_ordine(c)) if arts else 0
    n = fogli * c.copie_ordine
    return {
        "tipo": "ordine",
        "totale": n,                      # etichette da stampare
        "fogli": fogli,
        "copie": c.copie_ordine,
        "capi": c.totale,
        "richiede_conferma_extra": n > LIMITE_CONFERMA,
        "articoli": [{"descrizione": d, "totale": sum(q for _, q in r)} for d, r in arts],
        "righe": [{"articolo": i, "descrizione": d, "taglia": t, "capi": q}
                  for i, (d, r) in enumerate(arts) for t, q in r],
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
    return f"{'riepilogo' if c.tipo == 'ordine' else 'etichette'}_{base[:60]}.pdf"


@app.post("/api/pdf")
def pdf(c: Commessa):
    if c.totale == 0:
        raise HTTPException(400, "Nessuna etichetta da generare.")
    data = render_pdf(tutte_le_etichette(c, storage.leggi_impostazioni()))
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_nome_file(c)}"'})


# ---------------------------------------------------------------- stampa di rete
class RichiestaStampa(BaseModel):
    commessa: Commessa
    da_indice: int = 1               # per riprendere un job interrotto
    conferma_extra: bool = False     # seconda conferma oltre LIMITE_CONFERMA
    storico_id: Optional[int] = None # ristampa (o ripresa) di una commessa già nello storico
    # la commessa viene dal modulo dopo "Salva per dopo": se è ancora una bozza la si
    # aggiorna con i dati attuali, se intanto è stata stampata se ne crea una nuova
    aggiorna_bozza: bool = False


@app.post("/api/stampa")
def stampa(r: RichiestaStampa):
    imp = storage.leggi_impostazioni()
    tutte = tutte_le_etichette(r.commessa, imp)       # solo dati: disegnate nel thread del job
    tot = len(tutte)
    if tot == 0:
        raise HTTPException(400, "Nessuna etichetta da stampare.")
    if not 1 <= r.da_indice <= tot:
        raise HTTPException(400, f"L'etichetta di partenza deve essere tra 1 e {tot}.")
    da_stampare = tutte[r.da_indice - 1:]
    if len(da_stampare) > LIMITE_CONFERMA and not r.conferma_extra:
        raise HTTPException(409, f"{len(da_stampare)} etichette: serve la seconda conferma.")
    if not imp.ip_stampante:
        raise HTTPException(400, "IP della stampante non impostato: vai in Impostazioni.")
    if any(j.stato in ("in_coda", "in_corso") for j in printer.JOBS.values()):
        raise HTTPException(409, "C'è già una stampa in corso.")
    if r.storico_id is not None and not storage.leggi_commessa(r.storico_id):
        raise HTTPException(404, "Commessa non trovata nello storico.")
    if r.storico_id is None:
        cid = storage.salva_commessa(r.commessa)
    elif r.aggiorna_bozza and not storage.aggiorna_bozza(r.storico_id, r.commessa):
        cid = storage.salva_commessa(r.commessa)
    else:
        cid = r.storico_id
    sid = storage.registra_stampa(cid, r.commessa, r.da_indice, tot)
    immagini = da_stampare
    job = printer.avvia_job(immagini, tot, r.da_indice, imp,
                            al_termine=lambda j: storage.chiudi_stampa(sid, j.stato, j.inviate, j.errore))
    job.commessa_id = cid
    return job.pubblico()


@app.get("/api/stampa/{job_id}")
def stato_job(job_id: str):
    job = printer.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Stampa non trovata.")
    return job.pubblico()


@app.post("/api/stampa/{job_id}/annulla")
def annulla_job(job_id: str):
    job = printer.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Stampa non trovata.")
    job.annulla = True
    return job.pubblico()


@app.get("/api/stampante/stato")
def stato_stampante():
    return printer.stato_stampante(storage.leggi_impostazioni())


@app.post("/api/stampante/prova")
def stampa_prova():
    imp = storage.leggi_impostazioni()
    if not imp.ip_stampante:
        raise HTTPException(400, "IP della stampante non impostato.")
    img = render_label("Prova di stampa", "Etichetta di prova", "M", 1, 1, True, imp.contatore,
                       compensazione=imp.compensazione)
    return printer.avvia_job([img], 1, 1, imp).pubblico()


LIVELLI_COMPENSAZIONE = [0.0, 0.15, 0.25, 0.35]


@app.post("/api/stampante/prova-compensazione")
def stampa_prova_compensazione():
    """Quattro etichette S, una per livello: si sceglie quella che stampata è più nitida."""
    imp = storage.leggi_impostazioni()
    if not imp.ip_stampante:
        raise HTTPException(400, "IP della stampante non impostato.")
    n = len(LIVELLI_COMPENSAZIONE)
    imgs = [render_label("Prova compensazione", f"Livello {c:.2f}".replace(".", ","), "S", i + 1, n,
                         True, True, compensazione=c) for i, c in enumerate(LIVELLI_COMPENSAZIONE)]
    return printer.avvia_job(imgs, n, 1, imp).pubblico()


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
    compensazione: Optional[float] = None
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
    if "compensazione" in dati and not 0 <= dati["compensazione"] <= 0.45:
        raise HTTPException(400, "Compensazione fuori intervallo.")
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


# ---------------------------------------------------------------- storico
@app.get("/api/storico")
def storico(q: str = Query("", max_length=200), stato: str = Query("", pattern="^(|bozze|stampate)$")):
    return storage.elenco_commesse(q, stato=stato)


@app.get("/api/storico/{cid}")
def storico_dettaglio(cid: int):
    d = storage.leggi_commessa(cid)
    if not d:
        raise HTTPException(404, "Commessa non trovata.")
    return d


def _da_salvare(c: Commessa) -> Commessa:
    if c.totale == 0:
        raise HTTPException(400, "Niente da salvare: aggiungi almeno un articolo con una taglia.")
    return c


@app.post("/api/storico")
def salva_per_dopo(c: Commessa):
    """Salva la commessa senza stamparla: compare nello storico tra quelle da stampare."""
    return {"id": storage.salva_commessa(_da_salvare(c)), "nuova": True}


@app.put("/api/storico/{cid}")
def aggiorna_salvata(cid: int, c: Commessa):
    """Aggiorna una commessa salvata per dopo; se intanto è stata stampata ne crea una nuova."""
    _da_salvare(c)
    if storage.aggiorna_bozza(cid, c):
        return {"id": cid, "nuova": False}
    return {"id": storage.salva_commessa(c), "nuova": True}


@app.delete("/api/storico/{cid}")
def elimina_salvata(cid: int):
    if not storage.leggi_commessa(cid):
        raise HTTPException(404, "Commessa non trovata.")
    if not storage.elimina_bozza(cid):
        raise HTTPException(409, "Una commessa già stampata non si può eliminare.")
    return {"ok": True}


# ---------------------------------------------------------------- import file d'ordine
MAX_FILE_IMPORT = 5 * 1024 * 1024


@app.post("/api/import")
async def importa(file: UploadFile = File(...)):
    contenuto = await file.read(MAX_FILE_IMPORT + 1)
    if len(contenuto) > MAX_FILE_IMPORT:
        raise HTTPException(413, "File troppo grande (massimo 5 MB).")
    nome = file.filename or ""
    try:
        imp = trova_importer(nome, contenuto)
        return imp.importa(contenuto, nome_file=nome).model_dump()
    except ImportNonDisponibile as e:
        raise HTTPException(422, str(e))


app.mount("/fonts", StaticFiles(directory=os.path.join(os.path.dirname(STATIC), "label", "assets", "fonts")),
          name="fonts")
if os.path.isdir(STATIC):
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
