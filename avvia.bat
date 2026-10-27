@echo off
rem FF Etichette - avvio su Windows: crea l'ambiente, installa le dipendenze, avvia.
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Serve Python 3.10 o piu' recente: https://www.python.org/downloads/  ^(spunta "Add python.exe to PATH"^)
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creo l'ambiente Python ^(.venv^)...
  %PY% -m venv .venv || goto errore
)

fc /b requirements.txt .venv\requirements.installati >nul 2>nul
if errorlevel 1 (
  echo Installo le dipendenze...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto errore
  copy /y requirements.txt .venv\requirements.installati >nul
)

".venv\Scripts\python.exe" -m app
goto :eof

:errore
echo.
echo Installazione non riuscita. Controlla il messaggio qui sopra e il README.
pause
exit /b 1
