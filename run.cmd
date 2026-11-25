@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Unstructured Data Console - start the server (Windows x64). Install first with setup.cmd.
rem All logic lives in scripts\console.py. This file only runs it with backend\.venv.
pushd "%~dp0" || exit /b 1
if /i "%~1"=="--help" goto :help
if /i "%~1"=="-h" goto :help
if not exist "%~dp0backend\.venv\Scripts\python.exe" (
  echo [error] Not set up yet. Run setup.cmd first.
  popd
  if "%~1"=="" pause
  exit /b 1
)
"%~dp0backend\.venv\Scripts\python.exe" "%~dp0scripts\console.py" run %*
set "RESULT=%errorlevel%"
popd
if not "%RESULT%"=="0" if "%~1"=="" pause
exit /b %RESULT%

:help
echo Usage: run.cmd [port] [--no-browser]
echo   port          first port to try, default 8000. The next free port is used if it is busy.
echo   --no-browser  do not open the browser
echo Stop the server with Ctrl+C. Run setup.cmd first, and again after updating the code.
popd
exit /b 0
