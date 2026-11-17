@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1

for %%I in ("%~dp0.") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%"

set "INSTALL_EXTENDED=0"
set "NO_PAUSE=0"

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--extended" set "INSTALL_EXTENDED=1"
if /i "%~1"=="--no-pause" set "NO_PAUSE=1"
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage
shift
goto :parse_args

:args_done
echo ==============================================================================
echo  MarketStream - Real-Time Financial Data Intelligence Platform Setup
echo ==============================================================================
echo [INFO] Repository root: %REPO_ROOT%
echo.

echo [1/7] Checking Python 3.12+...
set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.12"
)
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=python"
    )
)
if not defined PY_CMD (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=py -3"
    )
)
if not defined PY_CMD (
    echo [ERROR] Python 3.12 or newer was not found on PATH or via the Python Launcher ^(py -3.12^).
    echo         Please install Python 3.12+ from https://www.python.org/downloads/ and retry.
    goto :fail
)
for /f "delims=" %%V in ('%PY_CMD% --version 2^>^&1') do set "PY_VER=%%V"
echo [OK] Using %PY_VER% ^(%PY_CMD%^)

echo.
echo [2/7] Checking Node.js and npm...
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js was not found on PATH. Install Node.js 18+ ^(LTS recommended^).
    goto :fail
)
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm was not found on PATH.
    goto :fail
)
for /f "delims=" %%V in ('node --version 2^>^&1') do set "NODE_VER=%%V"
for /f "delims=" %%V in ('call npm --version 2^>^&1') do set "NPM_VER=%%V"
echo [OK] Node.js %NODE_VER%, npm %NPM_VER%

echo.
echo [3/7] Preparing .env configuration and data directories...
if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo [OK] Created .env from .env.example
    ) else (
        echo [WARN] .env.example not found; continuing without creating .env
    )
) else (
    echo [OK] Existing .env preserved
)
for %%D in ("data" "data\bronze" "data\silver" "data\gold" "data\nats" "data\warehouse" "data\warehouse\staging" "data\warehouse\snapshots") do (
    if not exist "%%~D" mkdir "%%~D"
)
echo [OK] Local Medallion and NATS data directories verified

echo.
echo [4/7] Creating or verifying Python virtual environment ^(.venv^)...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Existing .venv uses Python older than 3.12. Delete the .venv folder and re-run setup.bat.
        goto :fail
    )
    echo [OK] Existing .venv verified ^(Python 3.12+^)
) else (
    %PY_CMD% -m venv ".venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create Python virtual environment in .venv
        goto :fail
    )
    echo [OK] Created .venv
)

echo.
echo [5/7] Installing Python dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip in .venv
    goto :fail
)
".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.txt
    goto :fail
)
if "%INSTALL_EXTENDED%"=="1" (
    if exist "requirements-extended.txt" (
        echo [INFO] Installing optional extended dependencies ^(requirements-extended.txt^)...
        ".venv\Scripts\python.exe" -m pip install -r "requirements-extended.txt"
        if errorlevel 1 (
            echo [ERROR] Failed to install requirements-extended.txt
            goto :fail
        )
    )
)
echo [OK] Python dependencies installed

echo.
echo [6/7] Installing NATS Server binary and applying Alembic migrations...
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\scripts\install_nats.ps1"
if errorlevel 1 (
    echo [ERROR] Failed to install or verify .bin\nats-server.exe
    goto :fail
)
set "PYTHONPATH=%REPO_ROOT%"
".venv\Scripts\alembic.exe" upgrade head
if errorlevel 1 (
    echo [ERROR] Alembic database migration failed
    goto :fail
)
echo [OK] NATS binary and database schema ready

echo.
echo [7/7] Installing frontend dependencies and building production bundle...
pushd "%REPO_ROOT%\frontend"
if exist "package-lock.json" (
    if not exist "node_modules" (
        call npm ci
    ) else (
        call npm install
    )
) else (
    call npm install
)
if errorlevel 1 (
    popd
    echo [ERROR] npm install failed in frontend\
    goto :fail
)
call npm run build
if errorlevel 1 (
    popd
    echo [ERROR] Frontend build ^(tsc ^&^& vite build^) failed
    goto :fail
)
popd
echo [OK] Frontend bundle compiled to frontend\dist\

echo.
echo ==============================================================================
echo  Setup Completed Successfully
echo ==============================================================================
echo  Next step: Run "run.bat" ^(or double-click run.bat^) to start the platform.
echo  Optional flags:
echo    setup.bat --extended   ^(also install MinIO/S3 ^& Prometheus extended libs^)
echo    run.bat --open         ^(start LITE platform and open browser dashboard^)
echo    run.bat standard       ^(run with STANDARD resource budget profile^)
echo ==============================================================================
goto :finish

:usage
echo Usage: setup.bat [--extended] [--no-pause]
exit /b 0

:fail
echo.
echo [FAILED] Setup encountered an error. Review the messages above.
if "%NO_PAUSE%"=="0" (
    echo %cmdcmdline% | findstr /i /c:"\"\"%~f0\"\"" >nul 2>&1
    if not errorlevel 1 pause
)
exit /b 1

:finish
if "%NO_PAUSE%"=="0" (
    echo %cmdcmdline% | findstr /i /c:"\"\"%~f0\"\"" >nul 2>&1
    if not errorlevel 1 pause
)
exit /b 0

