@echo off
rem FF Etichette - aggiornamento: ferma il servizio, scarica le novita', reinstalla le
rem dipendenze solo se requirements.txt e' cambiato, riavvia. Eseguire come amministratore.
setlocal
cd /d "%~dp0"

net session >nul 2>nul
if errorlevel 1 (
  echo Serve aprirlo come amministratore: tasto destro ^> Esegui come amministratore.
  pause
  exit /b 1
)

echo Fermo il servizio...
schtasks /End /TN "FF Etichette" >nul 2>nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.ExecutablePath -like 'C:\FF_Etichette\.venv\*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo Scarico gli aggiornamenti...
git pull --ff-only || goto errore

fc /b requirements.txt .venv\requirements.installati >nul 2>nul
if errorlevel 1 (
  echo Dipendenze cambiate: le reinstallo...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto errore
  copy /y requirements.txt .venv\requirements.installati >nul
) else (
  echo Dipendenze invariate.
)

echo Riavvio il servizio...
schtasks /Run /TN "FF Etichette" >nul || goto errore
echo Fatto. L'app torna disponibile tra qualche secondo.
pause
exit /b 0

:errore
echo.
echo Aggiornamento non riuscito. Riavvio comunque il servizio con la versione presente.
schtasks /Run /TN "FF Etichette" >nul 2>nul
pause
exit /b 1
