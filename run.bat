@echo off
rem Tank-G Control Center. Sin argumentos abre la interfaz grafica; con argumentos, la CLI.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Creando entorno .venv ...
    py -3 -m venv .venv || python -m venv .venv || goto :nopython
    .venv\Scripts\python -m pip install -q -r requirements.txt || goto :eof
)
if "%~1"=="" (
    start "" .venv\Scripts\pythonw.exe -m tankg
) else (
    .venv\Scripts\python.exe -m tankg %*
)
goto :eof
:nopython
echo No se encontro Python 3. Instalalo desde https://www.python.org/downloads/ (marca "Add to PATH").
pause
