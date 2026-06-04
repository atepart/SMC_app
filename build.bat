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

echo Building updater...
"%PYTHON_BIN%" -m PyInstaller updater.py -n updater --onefile --windowed --noconsole -y

echo Building main app...
"%PYTHON_BIN%" -m PyInstaller aocapp\__main__.py -n %app_name% --onedir --icon=".\assets\aocapp-icon.ico" --noconsole --windowed -y --add-data="assets;assets"

echo Bundling updater...
if exist "dist\updater.exe" (
    copy /Y "dist\updater.exe" "dist\%app_name%\updater.exe"
)

echo Build complete.
endlocal
