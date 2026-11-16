@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1

for %%I in ("%~dp0.") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%"

set "PROFILE=lite"
set "HOST=127.0.0.1"
set "PORT=8000"
set "NATS_PORT=4222"
set "NATS_HTTP_PORT=8222"
set "NATS_MEM_MB=64"
set "NATS_FILE_MB=128"
set "OPEN_BROWSER=0"
set "CHECK_ONLY=0"
set "STOP_ONLY=0"
set "NO_PAUSE=0"

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="lite" (
    set "PROFILE=lite"
    set "NATS_MEM_MB=64"
    set "NATS_FILE_MB=128"
    shift
    goto :parse_args
)
if /i "%~1"=="standard" (
    set "PROFILE=standard"
    set "NATS_MEM_MB=128"
    set "NATS_FILE_MB=512"
    shift
    goto :parse_args
)
if /i "%~1"=="extended" (
    set "PROFILE=extended"
    set "NATS_MEM_MB=256"
    set "NATS_FILE_MB=1024"
    shift
    goto :parse_args
)
if /i "%~1"=="--open" (
    set "OPEN_BROWSER=1"
    shift
    goto :parse_args
)
if /i "%~1"=="--check" (
    set "CHECK_ONLY=1"
    shift
    goto :parse_args
)
if /i "%~1"=="--stop" (
    set "STOP_ONLY=1"
    shift
    goto :parse_args
)
if /i "%~1"=="--no-pause" (
    set "NO_PAUSE=1"
    shift
    goto :parse_args
)
if /i "%~1"=="--port" (
    if not "%~2"=="" (
        set "PORT=%~2"
        shift
        shift
        goto :parse_args
    )
)
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage
echo [WARN] Ignoring unrecognized argument: %~1
shift
goto :parse_args

:args_done
if "%STOP_ONLY%"=="1" (
    echo [INFO] Stopping local NATS JetStream daemon...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\scripts\stop_nats.ps1"
    exit /b 0
)

echo ==============================================================================
echo  Crypto Financial Data Intelligence Platform v3.0.0 - Runtime Launcher
echo ==============================================================================
echo  Profile: %PROFILE% ^| Endpoint: http://%HOST%:%PORT%/
echo.

if not exist ".venv\Scripts\uvicorn.exe" (
    echo [ERROR] Python virtual environment not found at .venv\
    echo         Run "setup.bat" first to install dependencies and initialize the workspace.
    goto :fail
)
if not exist ".bin\nats-server.exe" (
    echo [WARN] NATS Server binary not found at .bin\nats-server.exe
    echo        Running scripts\install_nats.ps1...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\scripts\install_nats.ps1"
    if errorlevel 1 goto :fail
)
if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo [INFO] Created default .env from .env.example
    )
)
if not exist "frontend\dist\index.html" (
    echo [INFO] Static frontend bundle missing. Building frontend\dist\...
    pushd "%REPO_ROOT%\frontend"
    call npm run build
    if errorlevel 1 (
        popd
        echo [ERROR] Frontend production build failed.
        goto :fail
    )
    popd
)

set "PYTHONPATH=%REPO_ROOT%"
set "PLATFORM_PROFILE=%PROFILE%"

echo [1/4] Applying Alembic database migrations...
".venv\Scripts\alembic.exe" upgrade head
if errorlevel 1 (
    echo [ERROR] Database migration check failed.
    goto :fail
)

if "%CHECK_ONLY%"=="1" (
    echo [OK] Preflight checks passed for profile '%PROFILE%'.
    exit /b 0
)

echo [2/4] Starting NATS JetStream ^(port %NATS_PORT%, monitor %NATS_HTTP_PORT%^)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\scripts\start_nats.ps1" -Port %NATS_PORT% -HttpPort %NATS_HTTP_PORT% -MaxMemMb %NATS_MEM_MB% -MaxFileMb %NATS_FILE_MB%
if errorlevel 1 (
    echo [ERROR] Failed to start NATS JetStream.
    goto :fail
)

echo [3/4] Checking port %PORT% availability...
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
    echo [ERROR] Port %PORT% is already in use by another process.
    echo         Stop the conflicting service or run: run.bat --port 8080
    goto :fail
)

if "%OPEN_BROWSER%"=="1" call :launch_browser

echo [4/4] Starting FastAPI + Embedded Streaming Runtime + Static Dashboard...
echo.
echo   Dashboard : http://%HOST%:%PORT%/
echo   API Docs  : http://%HOST%:%PORT%/docs
echo   Metrics   : http://%HOST%:%PORT%/metrics
echo   NATS Info : http://127.0.0.1:%NATS_HTTP_PORT%/
echo.
echo Press Ctrl+C to stop the server.
echo ==============================================================================
".venv\Scripts\uvicorn.exe" backend.app.main:app --host %HOST% --port %PORT%
set "APP_EXIT=%ERRORLEVEL%"

echo.
echo [INFO] FastAPI exited ^(code %APP_EXIT%^). Cleaning up NATS JetStream...
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\scripts\stop_nats.ps1"
if not "%APP_EXIT%"=="0" goto :fail
goto :finish

:launch_browser
echo [INFO] Scheduling browser launch once http://%HOST%:%PORT%/api/v1/health is ready...
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "for ($i=0; $i -lt 30; $i++) { try { $r = Invoke-WebRequest -Uri 'http://%HOST%:%PORT%/api/v1/health' -UseBasicParsing -TimeoutSec 1; if ($r.StatusCode -eq 200) { Start-Process 'http://%HOST%:%PORT%/'; break } } catch {}; Start-Sleep -Milliseconds 500 }"
exit /b 0

:usage
echo Usage: run.bat [lite^|standard^|extended] [--port 8000] [--open] [--check] [--stop] [--no-pause]
exit /b 0

:fail
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
