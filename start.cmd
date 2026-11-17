@echo off
setlocal EnableExtensions
rem Unstructured Data Console - Windows launcher. First run creates backend\.venv and installs packages.
rem Usage: start.cmd [port]   (default port 8000)
cd /d "%~dp0"
set "VPY=%~dp0backend\.venv\Scripts\python.exe"
set "PORT=8000"
if not "%~1"=="" set "PORT=%~1"

if not exist "%VPY%" (
  call :create_venv
  if errorlevel 1 goto :fail
)
"%VPY%" -c "import fastapi, uvicorn, python_multipart" >nul 2>nul
if errorlevel 1 (
  call :install
  if errorlevel 1 goto :fail
)
if not exist ".env" if exist ".env.example" copy /y ".env.example" ".env" >nul
if exist "offline\docling-models" set "DOCOPS_DOCLING_ARTIFACTS=%~dp0offline\docling-models"
if not exist "frontend\dist\index.html" echo [warn] frontend\dist is missing. Use the offline bundle or run: cd frontend ^&^& npm ci ^&^& npm run build

echo.
echo   Unstructured Data Console  -  http://127.0.0.1:%PORT%/
echo   Model settings: .env  (restart after editing)   Stop: Ctrl+C
echo.
start "" "http://127.0.0.1:%PORT%/"
pushd backend
"%VPY%" -m uvicorn main:app --host 127.0.0.1 --port %PORT%
popd
exit /b %errorlevel%

:create_venv
set "PY="
for %%V in (3.12 3.13 3.14 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3.11 - 3.14 was not found.
  echo Install it, then run this file again:
  echo     winget install -e --id Python.Python.3.12
  exit /b 1
)
echo [setup] creating backend\.venv with %PY%
%PY% -m venv "%~dp0backend\.venv"
if errorlevel 1 exit /b 1
exit /b 0

:install
if exist "offline\wheels" (
  echo [setup] installing packages from offline\wheels
  "%VPY%" -m pip install --disable-pip-version-check --no-index --find-links offline\wheels -r backend\requirements.lock.txt
) else (
  echo [setup] installing packages from the package index
  "%VPY%" -m pip install --disable-pip-version-check -r backend\requirements.lock.txt
)
if errorlevel 1 exit /b 1
if exist "offline\wheels-docling" (
  echo [setup] installing optional Docling packages
  "%VPY%" -m pip install --disable-pip-version-check --no-index --find-links offline\wheels --find-links offline\wheels-docling -r backend\requirements-docling.lock.txt
  if errorlevel 1 exit /b 1
)
exit /b 0

:fail
echo.
echo Setup failed. Check the messages above.
pause
exit /b 1
