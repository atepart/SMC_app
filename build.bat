@echo off
setlocal

set "app_name=SMC_app"

if "%PYTHON_BIN%"=="" (
    if exist ".venv\Scripts\python.exe" (
        set "PYTHON_BIN=.venv\Scripts\python.exe"
    ) else (
        set "PYTHON_BIN=python"
    )
)

"%PYTHON_BIN%" -m PyInstaller aocapp\__main__.py -n %app_name% --onedir --icon=".\assets\aocapp-icon.ico" --noconsole --windowed -y --add-data="assets;assets"

endlocal
