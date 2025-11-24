@echo off
setlocal EnableExtensions

REM ============================================================
REM Relaunch in a persistent console so the window stays open
REM ============================================================
if /I not "%~1"=="/run" (
    start "LEAP Installer" cmd /k "%~f0 /run"
    goto :eof
)

REM ------------------ Config ------------------
set "REPO_URL=https://github.com/LLNL/LEAP/releases/download/v1.26/libleapct.dll"
set "DLL_NAME=libleapct.dll"
set "LEAP_DIR=%~dp0LEAP"
set "ENV_NAME=vamtoolbox-gpu"

REM Log location (unique per run)
set "LOG=%TEMP%\install_leap_%RANDOM%.log"
set "STEP_OUT=%TEMP%\install_leap_step_%RANDOM%.out"

call :log "===== Installing LEAP (easy path) ====="
call :log "Log: %LOG%"
echo.

REM ------------------------------------------------------------
REM Locate conda.bat so 'conda activate' works here
REM ------------------------------------------------------------
set "CONDA_BAT="
for %%P in (
    "%~dp0..\..\..\condabin\conda.bat"
    "C:\ProgramData\anaconda3\condabin\conda.bat"
    "%USERPROFILE%\anaconda3\condabin\conda.bat"
    "%USERPROFILE%\Miniconda3\condabin\conda.bat"
    "%ProgramData%\Miniconda3\condabin\conda.bat"
) do if exist "%%~fP" set "CONDA_BAT=%%~fP"
if not defined CONDA_BAT for /f "delims=" %%I in ('where conda.bat 2^>nul') do set "CONDA_BAT=%%~fI"
if not defined CONDA_BAT (
  call :log "ERROR: Could not find conda.bat. Open Anaconda Prompt and re-run."
  call :MsgBox "LEAP install" "Conda not found. Open Anaconda Prompt and re-run." 16
  goto :END_FAIL
)
call :log "Using conda launcher: %CONDA_BAT%"
call "%CONDA_BAT%" --version >> "%LOG%" 2>&1

REM --------------- Activate env ---------------
call :log "[1/8] Activating environment: %ENV_NAME%"
call "%CONDA_BAT%" activate %ENV_NAME% >> "%LOG%" 2>&1
if errorlevel 1 (
  call :log "ERROR: Failed to activate %ENV_NAME%."
  call :MsgBox "LEAP install" "Failed to activate %ENV_NAME%. Activate it manually, then re-run." 16
  goto :END_FAIL
)

REM --------------- Check Git ---------------
call :log "[2/8] Checking Git..."
where git >nul 2>&1 || (
  call :log "ERROR: Git not found on PATH. Install Git for Windows."
  call :MsgBox "LEAP install" "Git not found. Install Git for Windows, then re-run." 16
  goto :END_FAIL
)

REM --------------- Clone or update repo ---------------
call :log "[3/8] Preparing LEAP repo at: %LEAP_DIR%"
if not exist "%LEAP_DIR%\.git" (
  call :log "Cloning LLNL/LEAP ..."
  call :run git clone https://github.com/LLNL/LEAP.git "%LEAP_DIR%" || (
    call :log "ERROR: git clone failed. See log."
    call :MsgBox "LEAP install" "git clone failed. See the log." 16
    goto :END_FAIL
  )
) else (
  call :log "Repo already present. Pulling latest..."
  pushd "%LEAP_DIR%" >nul
  call :run git pull --ff-only
  popd >nul
)

REM --------------- Download DLL ---------------
call :log "[4/8] Downloading precompiled DLL..."
call :log "URL: %REPO_URL%"
call :run powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%REPO_URL%' -OutFile '%LEAP_DIR%\%DLL_NAME%' -UseBasicParsing" || (
  call :log "ERROR: DLL download failed. Place %DLL_NAME% in %LEAP_DIR% and re-run."
  call :MsgBox "LEAP install" "Download failed. Place libleapct.dll in the LEAP folder and re-run." 16
  goto :END_FAIL
)
if not exist "%LEAP_DIR%\%DLL_NAME%" (
  call :log "ERROR: %DLL_NAME% not found after download."
  call :MsgBox "LEAP install" "libleapct.dll missing after download." 16
  goto :END_FAIL
)

REM --------------- Run manual_install.py ---------------
call :log "[5/8] Running manual_install.py ..."
pushd "%LEAP_DIR%" >nul
call :run python manual_install.py
set "PYERR=%ERRORLEVEL%"
popd >nul
if not "%PYERR%"=="0" (
  call :log "ERROR: manual_install.py failed."
  call :MsgBox "LEAP install" "manual_install.py failed. See the log." 16
  goto :END_FAIL
)

REM --------------- Probe CUDA runtimes (cudart64_XXX.dll) ---------------
call :log "[6/8] Probing for CUDA runtime (cudart64_XXX.dll) and adding to PATH ..."
set "FOUND_RUNTIME="
for %%V in (130 125 122 121 120 118 117 116 115 110) do (
  for /f "delims=" %%D in ('dir /b /s "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\*\bin\cudart64_%%V.dll" 2^>nul') do (
    call :log "  found: %%D"
    set "PATH=%%~dpD;%PATH%"
    set "FOUND_RUNTIME=%%D"
    goto :HAVE_RUNTIME
  )
)
:HAVE_RUNTIME
if defined FOUND_RUNTIME (
  call :log "Using CUDA runtime: %FOUND_RUNTIME%"
) else (
  call :log "WARNING: No cudart64_*.dll found under default CUDA installs."
  call :log "If verification fails, install the CUDA runtime matching LEAP's build (try 11.8 -> cudart64_118.dll)."
)

REM --------------- Also add nvcc bin (generic fallback) ---------------
call :log "Locating system CUDA bin (fallback) ..."
set "CUDA_BIN="
for /f "delims=" %%I in ('where nvcc.exe 2^>nul') do set "CUDA_BIN=%%~dpI"
if defined CUDA_BIN (
  call :log "Using system CUDA bin: %CUDA_BIN%"
  set "PATH=%CUDA_BIN%;%PATH%"
) else (
  call :log "No system nvcc.exe found on PATH. Skipping system CUDA fallback."
)

REM --------------- Verify imports (DLL + leaptorch) ---------------
call :log "[7/8] Verifying Python import (leapctype -> CDLL -> leaptorch) ..."
set "PYCODE=import os,sys,ctypes,leapctype; p=os.path.join(os.path.dirname(leapctype.__file__),'libleapct.dll'); print('DLL:',p,'exists:',os.path.exists(p)); ctypes.CDLL(p); import leaptorch; print('LEAP OK ✅')"
call :run python -c "%PYCODE%"
if errorlevel 1 (
  call :log "ERROR: Verification failed. Missing/mismatched CUDA runtime (cudart)."
  call :log "TIP: Install the CUDA runtime that provides cudart64_118.dll (CUDA 11.8) and re-run."
  call :MsgBox "LEAP install" "Import failed (CUDA runtime missing/mismatch). See the log for details." 16
  goto :END_FAIL
)

call :log "SUCCESS: LEAP installed and import verified."
call :MsgBox "LEAP install" "Success! LEAP installed. Opening log..." 64
start "" notepad "%LOG%"
del "%STEP_OUT%" >nul 2>&1
goto :END_OK

REM --------------- Done ---------------
:END_FAIL
>> "%LOG%" echo ===== FAILED at %DATE% %TIME% =====
call :log "See log: %LOG%"
start "" notepad "%LOG%"
del "%STEP_OUT%" >nul 2>&1
exit /b 1

:END_OK
>> "%LOG%" echo ===== DONE at %DATE% %TIME% =====
exit /b 0

REM ----------------- Helpers -----------------
:log
setlocal EnableDelayedExpansion
set "MSG=%~1"
echo !MSG!
>> "%LOG%" echo !MSG!
endlocal
exit /b

:run
cmd /c %* > "%STEP_OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%STEP_OUT%"
type "%STEP_OUT%" >> "%LOG%"
exit /b %RC%

:MsgBox
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Add-Type -AssemblyName PresentationFramework;[System.Windows.MessageBox]::Show('%~2','%~1',[System.Windows.MessageBoxButton]::OK,[System.Windows.MessageBoxImage]::%3)" >nul 2>&1
exit /b
