@echo off
title Astrology Engine - Servidor API

echo ===================================================
echo   Iniciando Astrology Engine API
echo ===================================================
echo.

:: 1. Obtener la IP local de la computadora
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set IP=%%a
)
:: Limpiar espacios en blanco de la IP
set IP=%IP: =%

:: 2. Activar el entorno virtual Python
call .venv\Scripts\activate.bat

echo IP Detectada: %IP%
echo Servidor escuchando en: http://0.0.0.0:8000
echo Abrir Frontend desde PC / Telefono en: http://%IP%:8000/docs
echo.
echo Presiona Ctrl + C en esta ventana para detener el servidor.
echo ===================================================
echo.

:: 3. Ejecutar servidor Uvicorn
python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload

pause