"""Import della "Scheda di produzione" da PDF, scansione o foto.

- PDF esportato da Word: il testo si legge direttamente dal file (pdfplumber), con la posizione
  di ogni parola sulla pagina.
- PDF scansionato o foto (.jpg/.png): la pagina passa da Tesseract OCR, in locale (nessun
  servizio esterno). Serve il programma `tesseract` con la lingua italiana.

Dalle parole si ricostruiscono righe e celle in base alla posizione, poi si cercano le stesse
cose della scheda Word (vedi word.py): "Cliente", i titoli "Articolo N - X pz", le coppie
Articolo / Marca e codice / Colore capo e la riga delle taglie con sotto le quantità, abbinate
alla taglia per colonna. La commessa si compone come per il Word (`componi_scheda`).
"""
from __future__ import annotations

import io
import os
import shutil
import statistics
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Tuple

from .base import Importer, ImportNonDisponibile, MappaturaColonne, RisultatoImport
from .tabella import _norm, _taglia_da_intestazione
from .word import K_ARTICOLO, K_CLIENTE, K_CODICE, K_COLORE, _TITOLO, _primo, componi_scheda

ESTENSIONI_FOTO = (".jpg", ".jpeg", ".png")
MAX_PAGINE = 20
MAX_PAGINE_OCR = 6
DPI_OCR = 300
LATO_OCR = 3300             # pixel del lato lungo per l'OCR (~ A4 a 280 dpi): cifre abbastanza grandi
TIMEOUT_OCR = 90            # secondi per pagina
CHIAVI = sorted(K_CLIENTE + K_ARTICOLO + K_COLORE + K_CODICE, key=len, reverse=True)
TESSERACT_NOTI = [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                  "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract"]


@dataclass
class Parola:
    testo: str
    x0: float
    y0: float
    x1: float
    y1: float
    # solo per le parole lette con l'OCR: rilegge il riquadro ammettendo solo cifre
    rileggi: Optional[Callable[[], str]] = field(default=None, repr=False, compare=False)

    @property
    def h(self) -> float:
        return max(self.y1 - self.y0, 1.0)

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Riga:
    parole: List[Parola]
    celle: List[str]         # parole vicine unite: una cella di tabella o una frase
    h: float                 # altezza tipica del testo nella riga

    @property
    def yc(self) -> float:
        return statistics.median(p.yc for p in self.parole)

    @property
    def testo(self) -> str:
        return " ".join(self.celle)


# ---------------------------------------------------------------- parole dalla pagina
def _pulisci(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).split())


def _utile(s: str) -> bool:
    """Scarta i segni senza lettere né cifre (bordi letti dall'OCR, caselle ☐, trattini)."""
    return any(ch.isalnum() for ch in s)


def tesseract() -> Optional[str]:
    for p in [os.environ.get("FF_TESSERACT", ""), shutil.which("tesseract") or ""] + TESSERACT_NOTI:
        if p and os.path.isfile(p):
            return p
    return None


def _ocr(img) -> List[Parola]:
    """Parole di un'immagine con Tesseract (formato TSV: una riga per parola con il riquadro)."""
    exe = tesseract()
    if not exe:
        raise ImportNonDisponibile(
            "Per leggere PDF scansionati e foto serve Tesseract OCR, che su questo computer non è "
            "installato. Su Windows: winget install UB-Mannheim.TesseractOCR, più la lingua italiana "
            "(ita.traineddata). I PDF esportati da Word si leggono anche senza.")
    img = img.convert("L")
    if max(img.size) < LATO_OCR:              # foto piccola: ingrandisci, l'OCR legge meglio
        f = LATO_OCR / max(img.size)
        img = img.resize((round(img.width * f), round(img.height * f)))
    img = _togli_linee(_bianco_nero(_raddrizza(img)))
    lingue = "ita+eng" if _ha_lingua(exe, "ita") else "eng"
    tsv = _tesseract(exe, img, ["-l", lingue, "--psm", "6", "tsv"])
    parole = []
    for riga in tsv.splitlines()[1:]:
        c = riga.split("\t")
        if len(c) < 12 or c[0] != "5":
            continue
        testo = _pulisci(c[11])
        try:
            conf = float(c[10])
            x, y, w, h = (int(v) for v in c[6:10])
        except ValueError:
            continue
        if testo and _utile(testo) and conf >= 30:
            p = Parola(testo, x, y, x + w, y + h)
            p.rileggi = lambda p=p: _rileggi_cifre(exe, img, p)
            parole.append(p)
    return parole


def _tesseract(exe: str, img, argomenti: List[str]) -> str:
    with tempfile.TemporaryDirectory() as d:
        percorso = os.path.join(d, "pagina.png")
        img.save(percorso)
        try:
            r = subprocess.run([exe, percorso, "stdout"] + argomenti,
                               capture_output=True, timeout=TIMEOUT_OCR,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise ImportNonDisponibile("La lettura OCR ci mette troppo: prova con una foto più piccola o un PDF.")
        except OSError as e:
            raise ImportNonDisponibile(f"Tesseract OCR non parte: {e}")
    if r.returncode != 0:
        raise ImportNonDisponibile("Tesseract OCR non è riuscito a leggere la pagina.")
    return r.stdout.decode("utf-8", "replace")


def _rileggi_cifre(exe: str, img, p: Parola) -> str:
    """Rilegge solo il riquadro di una parola, ammettendo solo cifre (quantità lette male)."""
    from PIL import Image
    m = round(p.h * 0.35)
    ritaglio = img.crop((max(p.x0 - m, 0), max(p.y0 - m, 0), p.x1 + m, p.y1 + m))
    f = 32 / p.h                               # cifre alte ~32 px, la misura che Tesseract legge meglio
    ritaglio = ritaglio.resize((max(round(ritaglio.width * f), 1), max(round(ritaglio.height * f), 1)), Image.LANCZOS)
    tela = Image.new("L", (ritaglio.width + 60, ritaglio.height + 60), 255)   # margine bianco
    tela.paste(ritaglio, (30, 30))
    return _tesseract(exe, tela, ["--psm", "7", "-c", "tessedit_char_whitelist=0123456789"]).strip()


def _raddrizza(img):
    """Corregge una pagina storta di pochi gradi (foto o scansione): sceglie l'angolo per cui le
    righe di testo sono più nette, cioè il profilo orizzontale dei pixel scuri varia di più."""
    import numpy as np
    from PIL import Image
    piccola = img.copy()
    piccola.thumbnail((800, 800))
    inversa = piccola.point(lambda v: 255 if v < 140 else 0)

    def nitidezza(gradi):
        r = np.asarray(inversa.rotate(gradi, resample=Image.NEAREST), dtype=np.float32).sum(axis=1)
        return float(np.square(np.diff(r)).sum())

    migliore = max(np.arange(-5, 5.01, 0.5), key=nitidezza)
    migliore = max(np.arange(migliore - 0.4, migliore + 0.41, 0.1), key=nitidezza)
    if abs(migliore) < 0.15:
        return img
    return img.rotate(float(migliore), resample=Image.BICUBIC, expand=True, fillcolor=255)


def _bianco_nero(img):
    """Bianco e nero rispetto alla luminosità della zona (non una soglia unica): regge le ombre
    delle foto e toglie gli aloni grigi della compressione JPEG."""
    import numpy as np
    from PIL import Image, ImageFilter
    g = np.asarray(img, dtype=np.int16)
    media = np.asarray(img.filter(ImageFilter.BoxBlur(max(min(img.size) // 60, 8))), dtype=np.int16)
    return Image.fromarray(np.where((g < media - 25) & (g < 200), 0, 255).astype(np.uint8))


def _togli_linee(img):
    """Cancella i bordi delle tabelle (tratti scuri dritti più lunghi di ~5 mm su un A4):
    con i bordi l'OCR sbaglia o salta i caratteri singoli nelle celle (S, M, 1, 6…)."""
    import numpy as np
    from PIL import Image
    g = np.asarray(img).copy()
    scuro = g < 200            # soglia larga: i bordi sottili e sfumati restano continui
    L = max(min(g.shape) // 40, 15)

    def corse(m):
        """Pixel che stanno in una corsa orizzontale di almeno L pixel scuri."""
        c = np.cumsum(np.pad(m, ((0, 0), (1, 0))), axis=1, dtype=np.int32)
        piena = (c[:, L:] - c[:, :-L]) == L          # L pixel scuri a partire dalla colonna j
        cp = np.cumsum(np.pad(piena, ((0, 0), (1, 0))), axis=1, dtype=np.int32)
        j = np.arange(m.shape[1])
        da, a = np.clip(j - L + 1, 0, piena.shape[1]), np.clip(j + 1, 0, piena.shape[1])
        return (cp[:, a] - cp[:, da]) > 0

    linee = corse(scuro) | corse(scuro.T).T
    for _ in range(max(min(g.shape) // 800, 1)):     # più qualche pixel attorno: i bordi di una foto
        b = linee.copy()                             # non sono mai dritti al pixel
        b[1:] |= linee[:-1]; b[:-1] |= linee[1:]
        b[:, 1:] |= linee[:, :-1]; b[:, :-1] |= linee[:, 1:]
        linee = b
    g[linee] = 255
    return Image.fromarray(g)


_LINGUE: Dict[str, List[str]] = {}


def _ha_lingua(exe: str, lingua: str) -> bool:
    if exe not in _LINGUE:
        try:
            out = subprocess.run([exe, "--list-langs"], capture_output=True, timeout=20,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            _LINGUE[exe] = out.decode("utf-8", "replace").split()
        except (OSError, subprocess.TimeoutExpired):
            _LINGUE[exe] = []
    return lingua in _LINGUE[exe]


def _pagine_pdf(contenuto: bytes) -> Tuple[List[List[Parola]], int]:
    """Parole di ogni pagina e quante pagine sono state lette con l'OCR."""
    import pdfplumber
    pagine, ocr = [], 0
    try:
        with pdfplumber.open(io.BytesIO(contenuto)) as pdf:
            if len(pdf.pages) > MAX_PAGINE:
                raise ImportNonDisponibile(f"Il PDF ha {len(pdf.pages)} pagine: ne leggo al massimo {MAX_PAGINE}.")
            for pg in pdf.pages:
                parole = [Parola(t, w["x0"], w["top"], w["x1"], w["bottom"])
                          for w in pg.extract_words(x_tolerance=1.5, y_tolerance=2)
                          if (t := _pulisci(w["text"])) and _utile(t)]
                if len(parole) < 5:              # niente testo: è una scansione
                    ocr += 1
                    if ocr > MAX_PAGINE_OCR:
                        raise ImportNonDisponibile(
                            f"Il PDF scansionato ha troppe pagine: ne leggo al massimo {MAX_PAGINE_OCR}.")
                    parole = _ocr(pg.to_image(resolution=DPI_OCR).original)
                pagine.append(parole)
    except ImportNonDisponibile:
        raise
    except Exception as e:                       # pdfminer solleva eccezioni di vario tipo
        if "password" in str(e).lower() or type(e).__name__ == "PDFPasswordIncorrect":
            raise ImportNonDisponibile("Il PDF è protetto da password.")
        raise ImportNonDisponibile("Il PDF non si apre: è danneggiato?")
    return pagine, ocr


def _pagina_foto(contenuto: bytes) -> List[Parola]:
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        img = Image.open(io.BytesIO(contenuto))
        img = ImageOps.exif_transpose(img)        # foto del telefono: raddrizza
    except (UnidentifiedImageError, OSError):
        raise ImportNonDisponibile("L'immagine non si apre: usa una foto JPG o PNG.")
    return _ocr(img)


# ---------------------------------------------------------------- righe e celle
def righe(parole: List[Parola]) -> List[Riga]:
    """Raggruppa le parole in righe (stessa altezza sulla pagina) e, dentro la riga, in celle:
    tra due celle c'è più spazio che tra due parole della stessa frase."""
    out: List[List[Parola]] = []
    for p in sorted(parole, key=lambda p: p.yc):
        if out:
            cur = out[-1]
            yc = statistics.median(q.yc for q in cur)
            h = statistics.median(q.h for q in cur)
            if abs(p.yc - yc) <= 0.5 * max(h, p.h):
                cur.append(p)
                continue
        out.append([p])
    risultato = []
    for ps in out:
        ps.sort(key=lambda p: p.x0)
        h = statistics.median(p.h for p in ps)
        celle, prec = [], None
        for p in ps:
            if prec is not None and p.x0 - prec.x1 <= 0.8 * h:
                celle[-1] += " " + p.testo
            else:
                celle.append(p.testo)
            prec = p
        risultato.append(Riga(ps, celle, h))
    return risultato


# ---------------------------------------------------------------- lettura della scheda
def _chiavi_valori(r: Riga) -> Dict[str, str]:
    """Coppie "Etichetta | valore" della riga, solo per le etichette della scheda.
    Il valore è la cella dopo, oppure il resto della cella ("Cliente: Rossi")."""
    out: Dict[str, str] = {}
    ocr = r.parole[0].rileggi is not None
    for k, cella in enumerate(r.celle):
        n = _norm(cella)
        if _TITOLO.match(cella):
            continue
        if ocr and n not in CHIAVI:                  # OCR: "Articoto" è "Articolo"
            n = next((c for c in CHIAVI if len(c) >= 7 and SequenceMatcher(None, n, c).ratio() >= 0.8), n)
        for chiave in CHIAVI:
            if n == chiave:
                dopo = r.celle[k + 1] if k + 1 < len(r.celle) else ""
                if dopo and _norm(dopo) not in CHIAVI:
                    out.setdefault(chiave, dopo)
                break
            if n.startswith(chiave + " "):
                parole = cella.split()
                resto = " ".join(parole[len(chiave.split()):]).lstrip(":").strip()
                if resto:
                    out.setdefault(chiave, resto)
                break
    return out


def _numero(s: str) -> Optional[int]:
    """Quantità intera; corregge gli scambi tipici dell'OCR (O per 0, l o I per 1)."""
    t = s.strip().rstrip(".")
    if len(t) <= 4:
        t = t.translate(str.maketrans("OoIl|", "00111"))
    return int(t) if t.isdigit() else None


def _taglia(s: str) -> Optional[str]:
    t = _taglia_da_intestazione(s)
    if not t and len(s) == 2 and s[0].upper() == s[1].upper():
        t = _taglia_da_intestazione(s[0])     # l'OCR legge a volte "Ss" per una S grande
    return t


def _colonne_taglie(r: Riga) -> Optional[List[Tuple[str, float]]]:
    """[(taglia o "TOTALE", centro x)] se la riga è l'intestazione delle taglie."""
    col, altre = [], 0
    for p in r.parole:
        t = _taglia(p.testo)
        if t:
            col.append((t, p.xc))
        elif _norm(p.testo) in ("totale", "tot"):
            col.append(("TOTALE", p.xc))
        else:
            altre += 1
    taglie = sum(1 for t, _ in col if t != "TOTALE")
    return col if taglie >= 2 and taglie >= 1.5 * altre else None


def _quantita_sotto(col, rr: List[Riga], i: int, avvisi: List[str]):
    """Quantità sotto l'intestazione delle taglie, abbinate alla colonna più vicina.
    Restituisce (capi, totale dichiarato, indice della riga dopo la tabella)."""
    xs = sorted(x for _, x in col)
    passo = min((b - a for a, b in zip(xs, xs[1:])), default=100.0)
    capi: Dict[str, int] = {}
    totale, trovate = None, False
    y_prec = rr[i - 1].yc
    while i < len(rr) and rr[i].yc - y_prec <= 4 * rr[i].h:
        celle = []                                   # (parola, numero o None, colonna o None)
        for p in rr[i].parole:
            t, x = min(col, key=lambda c: abs(c[1] - p.xc))
            celle.append((p, _numero(p.testo), t if abs(x - p.xc) <= 0.6 * passo else None))
        numeri = sum(q is not None for _, q, _ in celle)
        dubbi = sum(q is None and t is not None for _, q, t in celle)
        if not numeri or dubbi > numeri:             # non è una riga di quantità
            break
        for p, q, t in celle:
            if q is None and t is not None and p.rileggi:
                q = _numero(p.rileggi())             # OCR: rileggi la cella da sola, solo cifre
            if t is None:
                if q is not None:
                    avvisi.append(f"quantità {q} fuori colonna, ignorata")
            elif q is None:
                avvisi.append(f"quantità illeggibile sotto {t.lower() if t == 'TOTALE' else 'la taglia ' + t} "
                              f"(«{p.testo}»), controlla")
            elif t == "TOTALE":
                totale = (totale or 0) + q
            elif q:
                capi[t] = capi.get(t, 0) + q
        trovate = True
        y_prec = rr[i].yc
        i += 1
    return (capi if trovate else {}), totale, i


def interpreta(pagine: List[List[Parola]]) -> Tuple[str, List[dict], List[str]]:
    nome = ""
    avvisi: List[str] = []
    articoli: List[dict] = []
    cur: Optional[dict] = None

    def nuovo(n_titolo=None, pz=None):
        a = {"n": n_titolo or len(articoli) + 1, "pz": pz, "kv": {}, "capi": None, "tot": None}
        articoli.append(a)
        return a

    for parole in pagine:
        rr = righe(parole)
        i = 0
        while i < len(rr):
            r = rr[i]
            m = _TITOLO.match(r.testo)
            if m:
                cur = nuovo(int(m.group(1)), int(m.group(2)) if m.group(2) else None)
                i += 1
                continue
            col = _colonne_taglie(r)
            if col:
                if cur is None or cur["capi"] is not None:
                    cur = nuovo()          # tabella taglie senza titolo "Articolo N"
                avv: List[str] = []
                cur["capi"], cur["tot"], i = _quantita_sotto(col, rr, i + 1, avv)
                avvisi += [f"Articolo {cur['n']}: {a}" for a in avv]
                continue
            kv = _chiavi_valori(r)
            if not nome:
                nome = _primo(kv, K_CLIENTE)
            if cur is not None and cur["capi"] is None:
                for k, v in kv.items():
                    if k not in K_CLIENTE:
                        cur["kv"].setdefault(k, v)
            i += 1
    return nome, articoli, avvisi


class ImporterPdf(Importer):
    nome = "Scheda di produzione (PDF, scansione o foto)"

    def riconosce(self, nome_file: str, contenuto: bytes) -> bool:
        n = nome_file.lower()
        return n.endswith(".pdf") or n.endswith(ESTENSIONI_FOTO) or contenuto[:5] == b"%PDF-"

    def colonne(self, contenuto: bytes) -> List[str]:
        return []

    def importa(self, contenuto: bytes, mappatura: Optional[MappaturaColonne] = None,
                nome_file: str = "ordine.pdf") -> RisultatoImport:
        if nome_file.lower().endswith(ESTENSIONI_FOTO):
            pagine, ocr = [_pagina_foto(contenuto)], 1
        else:
            pagine, ocr = _pagine_pdf(contenuto)
        if not any(pagine):
            raise ImportNonDisponibile("Nel file non trovo testo leggibile.")
        nome, articoli, avvisi = interpreta(pagine)
        if ocr:
            avvisi.insert(0, "Letto con l'OCR (scansione o foto): controlla bene nome, descrizioni e quantità.")
        return componi_scheda(articoli, nome, avvisi, nome_file)
