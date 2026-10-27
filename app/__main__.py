"""Avvio: python -m app  (lo usano avvia.sh / avvia.bat)."""
import os

import uvicorn

from .main import PORTA, indirizzo_lan


def main():
    ip = indirizzo_lan()
    riga = "=" * 56
    print(f"\n{riga}\n  FF Etichette è in funzione\n")
    print(f"  Da questo computer:  http://localhost:{PORTA}/")
    print(f"  Dal telefono (stessa rete Wi-Fi):  http://{ip}:{PORTA}/")
    print(f"\n  Per fermare il server: Ctrl+C\n{riga}\n", flush=True)
    uvicorn.run("app.main:app", host=os.environ.get("FF_HOST", "0.0.0.0"), port=PORTA,
                log_level="warning")


if __name__ == "__main__":
    main()
