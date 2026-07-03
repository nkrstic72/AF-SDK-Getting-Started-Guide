@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  AVEVA Docs Knowledge Base - One-Time Setup
echo ============================================================
echo.

:: ── Find Python ──────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://python.org and re-run.
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Found: %%v
echo.

:: ── Move to script directory ─────────────────────────────────
cd /d "%~dp0"

:: ── Install dependencies ─────────────────────────────────────
echo [1/3] Installing Python dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause & exit /b 1
)
echo.

:: ── Build the vector index ───────────────────────────────────
echo [2/3] Building the vector index (this will take 30-90 min for 10 GB)...
echo       You can leave this running and come back.
echo.
python index_docs.py
if errorlevel 1 (
    echo ERROR: Indexing failed. Check output above.
    pause & exit /b 1
)
echo.

:: ── Patch Claude Code settings ───────────────────────────────
echo [3/3] Configuring Claude Code MCP server...

set "SETTINGS=%APPDATA%\Claude\claude_desktop_config.json"
set "SERVER_PATH=%~dp0mcp_server.py"
:: Normalise backslashes for JSON (double them)
set "SERVER_JSON=%SERVER_PATH:\=\\%"

if not exist "%APPDATA%\Claude" mkdir "%APPDATA%\Claude"

if not exist "%SETTINGS%" (
    :: Create fresh settings file
    (
        echo {
        echo   "mcpServers": {
        echo     "aveva-docs": {
        echo       "command": "python",
        echo       "args": ["%SERVER_JSON%"]
        echo     }
        echo   }
        echo }
    ) > "%SETTINGS%"
    echo Created new settings file: %SETTINGS%
) else (
    :: Check if already configured
    findstr /c:"aveva-docs" "%SETTINGS%" >nul 2>&1
    if not errorlevel 1 (
        echo Claude Code already configured for aveva-docs. Skipping.
    ) else (
        echo.
        echo -------------------------------------------------------
        echo  MANUAL STEP NEEDED
        echo  Your Claude Code settings file already exists:
        echo    %SETTINGS%
        echo.
        echo  Add this block inside the "mcpServers": { } section:
        echo.
        echo    "aveva-docs": {
        echo      "command": "python",
        echo      "args": ["%SERVER_JSON%"]
        echo    }
        echo -------------------------------------------------------
    )
)

echo.
echo ============================================================
echo  Done! Restart Claude Code and the AVEVA docs MCP server
echo  will load automatically.
echo ============================================================
pause
