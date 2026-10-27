"""Stampa di rete sulla Brother QL-810W con brother_ql (raw TCP, porta 9100).

Un'intera commessa è un unico job raster. Il job viene scritto sul socket etichetta per
etichetta, così l'avanzamento è reale e, se la connessione cade, si sa da quale etichetta
ripartire. La stampante risponde alle richieste di stato (ESC i S) solo su alcuni firmware:
se risponde, rotolo sbagliato / fine etichette / coperchio aperto vengono segnalati in chiaro;
se non risponde, si controlla solo la raggiungibilità.
"""
from __future__ import annotations

import logging
import select
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from PIL import Image

from .models import Impostazioni

logging.getLogger("brother_ql").setLevel(logging.CRITICAL)   # niente rumore in console

from brother_ql.conversion import convert          # noqa: E402
from brother_ql.raster import BrotherQLRaster       # noqa: E402
from brother_ql.reader import interpret_response    # noqa: E402

PORTA = 9100
TIMEOUT_CONNESSIONE = 3.0
TIMEOUT_INVIO = 30.0

# Rotoli supportati, con l'identificativo di brother_ql. Valore: (larghezza, lunghezza) in mm come
# li riporta lo stato della stampante (0 = continuo), nome per i messaggi.
ROTOLI = {
    "62x100": ((62, 100), "DK-11202 fustellato 62 x 100 mm"),
    "62": ((62, 0), "continuo 62 mm (DK-22205)"),
    "62red": ((62, 0), "continuo nero/rosso 62 mm (DK-22251)"),
}
# Sul continuo l'etichetta si taglia a 100 mm come la fustellata. brother_ql aggiunge un avanzamento
# di 35 dot (feed_margin) in testa e in coda: 100 mm = 1181 dot, quindi 1111 righe di immagine.
# L'etichetta (1109 righe) viene centrata con 1 riga bianca sopra e sotto: grafica identica.
LUNGHEZZA_CONTINUO_MM = 100
MARGINE_CONTINUO = 35
RIGHE_CONTINUO = round(LUNGHEZZA_CONTINUO_MM / 25.4 * 300) - 2 * MARGINE_CONTINUO

ERRORI_IT = {
    "No media when printing": "Etichette finite o rotolo non inserito.",
    "End of media (die-cut size only)": "Fine del rotolo di etichette.",
    "Tape cutter jam": "Taglierina inceppata.",
    "Main unit in use": "La stampante è occupata.",
    "Printer turned off": "La stampante è spenta.",
    "High-voltage adapter": "Problema di alimentazione.",
    "Fan doesn't work": "Ventola guasta.",
    "Replace media error": "Il rotolo nella stampante non è quello impostato: controlla Impostazioni › Etichetta.",
    "Expansion buffer full": "Memoria della stampante piena.",
    "Transmission/Communication error": "Errore di comunicazione con la stampante.",
    "Communication buffer full": "Memoria di comunicazione piena.",
    "Cover opened while printing": "Coperchio aperto durante la stampa.",
    "Cancel key": "Stampa annullata dal tasto sulla stampante.",
    "Media cannot be fed": "Le etichette non avanzano: controlla il rotolo.",
    "System error": "Errore di sistema della stampante.",
}


class ErroreStampante(Exception):
    pass


# ---------------------------------------------------------------- raster
class _RasterConIndici(BrotherQLRaster):
    """Ricorda dove finisce ogni etichetta nel flusso raster."""
    def __init__(self, model):
        super().__init__(model)
        self.fine_pagine: List[int] = []
        self.exception_on_warning = True

    def add_print(self, last_page=True):
        super().add_print(last_page)
        self.fine_pagine.append(len(self.data))


def per_rotolo(img: Image.Image, etichetta: str) -> Image.Image:
    """Adatta l'etichetta 696x1109 al rotolo: sul continuo la porta a RIGHE_CONTINUO righe
    (taglio a 100 mm); sul nero/rosso la passa in RGB (brother_ql separa nero e rosso dai colori)."""
    if etichetta in ("62", "62red"):
        sopra = (RIGHE_CONTINUO - img.height) // 2
        nuova = Image.new(img.mode, (img.width, RIGHE_CONTINUO), 1 if img.mode == "1" else 255)
        nuova.paste(img, (0, sopra))
        img = nuova
    if etichetta == "62red":
        img = img.convert("RGB")
    return img


def raster(immagini: List[Image.Image], imp: Impostazioni) -> tuple[bytes, List[int]]:
    """Flusso raster di un unico job + offset di fine di ogni etichetta."""
    qlr = _RasterConIndici(imp.modello)
    convert(qlr, [per_rotolo(i, imp.etichetta) for i in immagini], imp.etichetta, cut=True, dither=False,
            compress=True, red=imp.etichetta == "62red", rotate="0", dpi_600=False, hq=True, threshold=50)
    data = bytearray(qlr.data)
    # brother_ql 0.9 chiude ogni pagina con 0x1A (fine job): per avere un unico job
    # le pagine intermedie devono finire con 0x0C (form feed), solo l'ultima con 0x1A.
    for end in qlr.fine_pagine[:-1]:
        assert data[end - 1] == 0x1A
        data[end - 1] = 0x0C
    return bytes(data), qlr.fine_pagine


# ---------------------------------------------------------------- stato stampante
def _connetti(ip: str) -> socket.socket:
    if not ip:
        raise ErroreStampante("IP della stampante non impostato: vai in Impostazioni.")
    try:
        s = socket.create_connection((ip, PORTA), timeout=TIMEOUT_CONNESSIONE)
    except socket.timeout:
        raise ErroreStampante(f"Stampante non raggiungibile su {ip}: nessuna risposta. "
                              "È accesa e sulla stessa rete Wi-Fi?")
    except OSError as e:
        raise ErroreStampante(f"Stampante non raggiungibile su {ip} ({e.strerror or e}).")
    s.settimeout(TIMEOUT_INVIO)
    return s


def _leggi_stati(s: socket.socket, attesa: float) -> List[dict]:
    """Legge le risposte di stato (32 byte) eventualmente arrivate entro `attesa` secondi."""
    buf = b""
    fine = time.monotonic() + attesa
    while True:
        rest = fine - time.monotonic()
        if rest <= 0:
            break
        r, _, _ = select.select([s], [], [], rest)
        if not r:
            break
        chunk = s.recv(256)
        if not chunk:
            break
        buf += chunk
        if len(buf) >= 32 and attesa == 0:
            break
    stati = []
    while len(buf) >= 32:
        i = buf.find(b"\x80\x20\x42")
        if i < 0:
            break
        try:
            stati.append(interpret_response(buf[i:i + 32]))
        except Exception:
            pass
        buf = buf[i + 32:]
    return stati


def problemi(stato: dict, imp: Impostazioni) -> List[str]:
    out = [ERRORI_IT.get(e, e) for e in stato.get("errors", [])]
    atteso, nome = ROTOLI.get(imp.etichetta, (None, ""))
    w, l = stato.get("media_width"), stato.get("media_length")
    if atteso and w and (w, l or 0) != atteso and not any("rotolo" in m.lower() for m in out):
        c_è = f"{w} mm continuo" if not l else f"{w}x{l} mm"
        out.append(f"Rotolo sbagliato: nella stampante c'è un {c_è}, è impostato {nome}. "
                   "Cambia rotolo o scegli quello giusto in Impostazioni › Etichetta.")
    return out


def stato_stampante(imp: Impostazioni) -> dict:
    """Raggiungibilità + stato dettagliato se la stampante lo fornisce."""
    try:
        s = _connetti(imp.ip_stampante)
    except ErroreStampante as e:
        return {"raggiungibile": False, "messaggio": str(e), "dettaglio": None}
    try:
        s.sendall(b"\x00" * 200 + b"\x1b\x40" + b"\x1b\x69\x53")   # invalidate, init, ESC i S
        stati = _leggi_stati(s, 1.5)
    except OSError:
        stati = []
    finally:
        s.close()
    if not stati:
        return {"raggiungibile": True, "dettaglio": None,
                "messaggio": "Stampante raggiungibile (non ha inviato lo stato del rotolo)."}
    st = stati[-1]
    prob = problemi(st, imp)
    return {"raggiungibile": True, "dettaglio": st, "pronta": not prob,
            "messaggio": " ".join(prob) if prob else
            f"Stampante pronta, rotolo {st.get('media_width')}x{st.get('media_length')} mm."}


# ---------------------------------------------------------------- job
@dataclass
class Job:
    id: str
    totale: int                      # etichette della commessa
    da_indice: int                   # prima etichetta di questo job (1-based)
    stato: str = "in_coda"           # in_coda | in_corso | completato | errore | annullato
    inviate: int = 0                 # etichette completamente inviate (conteggio sulla commessa)
    errore: Optional[str] = None
    annulla: bool = False
    preparazione: bool = True        # etichette in disegno, invio non ancora iniziato
    creato: float = field(default_factory=time.time)
    commessa_id: Optional[int] = None

    @property
    def prossimo_indice(self) -> int:
        return self.inviate + 1

    def pubblico(self) -> dict:
        return {"id": self.id, "stato": self.stato, "totale": self.totale, "da_indice": self.da_indice,
                "inviate": self.inviate, "prossimo_indice": self.prossimo_indice, "errore": self.errore,
                "preparazione": self.preparazione,
                "commessa_id": self.commessa_id}


JOBS: Dict[str, Job] = {}


def _disegna(voci: List) -> List[Image.Image]:
    from .label.label import Etichetta, EtichettaOrdine, render_etichetta
    cache: Dict[object, Image.Image] = {}
    out = []
    for v in voci:
        if isinstance(v, (Etichetta, EtichettaOrdine)):
            if v not in cache:
                cache[v] = render_etichetta(v)
            v = cache[v]
        out.append(v)
    return out
_lock_stampa = threading.Lock()      # un job alla volta verso la stampante


def avvia_job(immagini: List, totale: int, da_indice: int, imp: Impostazioni,
              al_termine: Optional[Callable[[Job], None]] = None) -> Job:
    """`immagini`: PIL.Image già pronte oppure `Etichetta`/`EtichettaOrdine` da disegnare nel thread del job
    (le etichette uguali, es. 5 copie della stessa taglia, vengono disegnate una volta sola)."""
    job = Job(id=uuid.uuid4().hex[:12], totale=totale, da_indice=da_indice, inviate=da_indice - 1)
    JOBS[job.id] = job
    # pulizia dei job vecchi
    for k in [k for k, j in JOBS.items() if time.time() - j.creato > 24 * 3600]:
        JOBS.pop(k, None)
    t = threading.Thread(target=_esegui, args=(job, immagini, imp, al_termine), daemon=True)
    t.start()
    return job


def _esegui(job: Job, immagini, imp: Impostazioni, al_termine):
    with _lock_stampa:
        job.stato = "in_corso"
        s = None
        try:
            immagini = _disegna(immagini)
            data, fine = raster(immagini, imp)
            job.preparazione = False
            s = _connetti(imp.ip_stampante)
            # stato prima di stampare, se la stampante lo fornisce
            s.sendall(b"\x00" * 200 + b"\x1b\x40" + b"\x1b\x69\x53")
            for st in _leggi_stati(s, 1.0):
                prob = problemi(st, imp)
                if prob:
                    raise ErroreStampante(" ".join(prob))
            inizio = 0
            for k, end in enumerate(fine):
                if job.annulla:
                    job.stato = "annullato"
                    job.errore = f"Stampa interrotta. Inviate {job.inviate} etichette su {job.totale}."
                    break
                s.sendall(data[inizio:end])
                inizio = end
                for st in _leggi_stati(s, 0):
                    prob = problemi(st, imp)
                    if prob:
                        raise ErroreStampante(" ".join(prob))
                job.inviate = job.da_indice + k
            else:
                # ultime risposte di stato (errori a fine job, es. etichette finite)
                for st in _leggi_stati(s, 1.0):
                    prob = problemi(st, imp)
                    if prob:
                        raise ErroreStampante(" ".join(prob))
                job.stato = "completato"
        except ErroreStampante as e:
            job.stato, job.errore = "errore", str(e)
        except (socket.timeout, TimeoutError):
            job.stato = "errore"
            job.errore = (f"La stampante ha smesso di ricevere dopo {job.inviate} etichette inviate su {job.totale}: "
                          "le ultime inviate potrebbero non essere state stampate. "
                          "Controlla il rotolo e le etichette uscite, poi riprendi.")
        except OSError as e:
            job.stato = "errore"
            job.errore = (f"Connessione con la stampante persa dopo {job.inviate} etichette inviate su {job.totale} "
                          f"({e.strerror or e}).")
        except Exception as e:      # conversione o altro errore inatteso
            job.stato, job.errore = "errore", f"Errore inatteso: {e}"
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        if al_termine:
            try:
                al_termine(job)
            except Exception:
                logging.getLogger(__name__).exception("al_termine")
