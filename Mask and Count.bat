@echo off
rem Double-click to start Mask and Count. The first run sets up .venv (a few minutes).
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 main.py %*
) else (
    python main.py %*
)
if errorlevel 1 (
    echo.
    echo Mask and Count exited with an error; see the messages above.
    pause
)
