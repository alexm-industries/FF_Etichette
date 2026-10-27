# FF Etichette

Webapp locale per preparare le etichette delle buste Fortitude Fabrics e stamparle sulla
**Brother QL-810W** (Wi-Fi), su etichette fustellate **DK-11202 62 x 100 mm**.
Si usa dal computer dell'ufficio e dal telefono sulla stessa rete Wi-Fi.

## Avvio

| Sistema | Comando |
| --- | --- |
| macOS | doppio clic su `avvia.sh` oppure `./avvia.sh` dal Terminale |
| Windows | doppio clic su `avvia.bat` |

Al primo avvio viene creato l'ambiente Python in `.venv` e vengono installate le dipendenze
(un paio di minuti). Poi il terminale mostra due indirizzi:

```
  Da questo computer:  http://localhost:8000/
  Dal telefono (stessa rete Wi-Fi):  http://192.168.1.23:8000/
```

Nella home, su computer, c'è anche un QR code da inquadrare col telefono. Dal telefono si può
"Aggiungere alla schermata Home" (Safari: Condividi → Aggiungi a Home; Chrome: menu → Installa app).

La porta si cambia con la variabile `FF_PORT` (es. `FF_PORT=8080 ./avvia.sh`).

## Prerequisiti

- **Python 3.10 o più recente.**
  - macOS: `brew install python` (serve [Homebrew](https://brew.sh)).
  - Windows: installer da [python.org](https://www.python.org/downloads/), spuntando *Add python.exe to PATH*.
- **Cairo** (la libreria grafica usata per disegnare l'etichetta):
  - macOS: `brew install cairo pkg-config` **prima** del primo avvio.
  - Windows: niente da fare, `pycairo` installa già la libreria.
  - Linux: `sudo apt install libcairo2-dev pkg-config python3-dev`.
- Il computer deve restare acceso e collegato alla stessa rete della stampante.
- Al primo avvio su macOS/Windows il sistema può chiedere di consentire le connessioni in entrata
  a Python: rispondi **Consenti**, altrimenti il telefono non raggiunge l'app.

## Trovare l'IP della stampante

1. Sulla QL-810W tieni premuto il tasto **Taglio (✂)** per circa un secondo: stampa il
   rapporto con le impostazioni di rete (se non succede nulla, nel manuale cerca
   "rapporto impostazioni stampante"). L'IP è alla voce **IP Address** (es. `192.168.1.50`).
2. In alternativa: pannello del router (elenco dispositivi, nome tipo `BRW…`), oppure su
   Windows *Impostazioni → Bluetooth e dispositivi → Stampanti*, proprietà della stampante.
3. Inserisci l'IP in **Impostazioni** nell'app, premi **Verifica stampante**, poi
   **Stampa etichetta di prova**.

Conviene assegnare alla stampante un **IP fisso** (prenotazione DHCP nel router), così non cambia.

## Uso

1. **Nuova**: scrivi la commessa, aggiungi gli articoli e per ogni articolo le taglie con le copie
   ("Altra…" per taglie come 4XL o 8-10A). L'anteprima mostra l'etichetta della riga selezionata.
2. **Stampa N etichette** → riepilogo nell'ordine di stampa → conferma. Oltre 200 etichette c'è
   una seconda conferma. Se la stampa si interrompe, puoi riprendere da un'etichetta precisa.
3. **Scarica PDF**: una pagina 62 x 100 mm per etichetta, stesso ordine, da stampare col driver
   Brother se la rete non va.
4. **Storico**: cerca, apri, duplica una commessa per modificarla, ristampa tutto o solo alcune righe.

Ordine di stampa: articolo per articolo; dentro l'articolo le taglie dalla più piccola alla più
grande (taglie bimbo come 4-6A e 8-10A, poi XS…3XL, poi 4XL, 5XL…, poi le altre personalizzate).

### Singolo capo / Intero ordine

In alto nel modulo si sceglie il tipo di etichetta:

- **Singolo capo**: un'etichetta per busta, come sopra (il numero accanto alla taglia = etichette).
- **Intero ordine**: un'etichetta di **riepilogo** da mettere sulla scatola o busta di consegna.
  Stessa testata e stesso piede, fascia nera con il nome commessa, poi per ogni articolo le caselle
  taglia con il numero di capi (il numero accanto alla taglia = capi). In fondo il totale capi.
  - **Copie dell'etichetta**: una per collo; con **Numera i colli** in testata compare "COLLO 1/3".
  - Se gli articoli non stanno su un'etichetta, il riepilogo continua su più fogli ("foglio 1/2 · segue").

### Salva per dopo

**Salva per dopo** (in fondo al modulo) mette la commessa nello storico senza stamparla. In
**Storico → Da stampare** si apre e si sceglie **Stampa**, **Modifica** o **Elimina**. Una volta
stampata non si modifica più: si ristampa o si duplica.

### Importa file

**Importa file** legge un file CSV o Excel (.xlsx) e compila il modulo, da controllare prima di
stampare. Le colonne si riconoscono dal nome dell'intestazione:

- una riga per articolo e taglia: `Articolo | (Grammatura) | (Colore) | Taglia | Quantità`;
- oppure una colonna per taglia: `Articolo | (Colore) | XS | S | M | L | …`.

Facoltativa una colonna `Commessa` (o `Ordine`, `Cliente`): se manca, il nome è quello del file.
Il formato definitivo del file d'ordine Fortitude va ancora fissato su un file reale.

## Impostazioni

- IP, modello ed etichetta della stampante.
- **Mostra il nome commessa** accanto all'articolo sull'etichetta (sì/no).
- **Contatore "3/5"** sull'etichetta (default spento).
- **Compensazione stampa termica**: la stampante ingrassa leggermente il nero e il grassetto
  piccolo si chiude (la S può sembrare un 8). "Stampa prova compensazione" stampa 4 etichette
  S con livelli diversi: scegli quella più nitida.
- **PIN** opzionale (4-8 cifre) per l'accesso dall'app.

L'app risponde solo a indirizzi della rete locale (192.168.x.x, 10.x.x.x, 172.16-31.x.x).

## Stampa: cosa controlla l'app

- Stampante non raggiungibile (spenta, IP sbagliato, altra rete).
- Rotolo sbagliato, etichette finite, coperchio aperto, taglierina: **solo se la stampante
  risponde alla richiesta di stato via rete**. Non tutti i firmware lo fanno: in quel caso
  l'app controlla solo la raggiungibilità e, se il job si interrompe, propone di riprendere.

Ogni commessa è un unico job; l'avanzamento indica le etichette inviate alla stampante.

## Sviluppo

```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/python -m app
```

- `app/label/label.py`: disegno dell'etichetta (dal template in `docs/template/`).
- `app/main.py`: API FastAPI; `app/printer.py`: stampa di rete; `app/storage.py`: SQLite in `data/`.
- `app/importers/`: predisposto per l'import dei file d'ordine (fase 2).
- `app/static/`: interfaccia (HTML/CSS/JS, nessuna build).
