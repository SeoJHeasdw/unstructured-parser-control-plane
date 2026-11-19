@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Unstructured Data Console - Windows x64 launcher.
pushd "%~dp0" || exit /b 1

if /i "%~1"=="--help" goto :help
rem Python installation remains a separate WinGet step.
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
set "PYLAUNCHER_ALLOW_INSTALL="
set "PYLAUNCHER_ALWAYS_INSTALL="
py -3.12 -c "import sysconfig; raise SystemExit(sysconfig.get_platform() != 'win-amd64')" >nul 2>nul
if not errorlevel 1 (
  py -3.12 "%~dp0scripts\windows_launcher.py" %*
  goto :finished
)
for %%P in ("%LocalAppData%\Programs\Python\Python312\python.exe" "%ProgramFiles%\Python312\python.exe") do (
  if exist "%%~P" (
    "%%~P" -c "import sysconfig; raise SystemExit(sysconfig.get_platform() != 'win-amd64')" >nul 2>nul
    if not errorlevel 1 (
      "%%~P" "%~dp0scripts\windows_launcher.py" %*
      goto :finished
    )
  )
)
for %%V in (3.13 3.14 3.15) do (
  py -%%V -c "import sysconfig; raise SystemExit(sysconfig.get_platform() != 'win-amd64')" >nul 2>nul
  if not errorlevel 1 (
    py -%%V "%~dp0scripts\windows_launcher.py" %*
    goto :finished
  )
)
python -c "import sys, sysconfig; raise SystemExit(not ((3,12) <= sys.version_info[:2] <= (3,15) and sysconfig.get_platform() == 'win-amd64'))" >nul 2>nul
if not errorlevel 1 (
  python "%~dp0scripts\windows_launcher.py" %*
  goto :finished
)

echo [setup] Windows x64 Python 3.12-3.15 is required. Use 3.12 for Docling.
echo     winget install --exact --id Python.Python.3.12 --architecture x64
echo Open a new terminal after installation.
popd
if "%~1"=="" pause
exit /b 1

:help
echo Usage: start.cmd [port] [--offline] [--docling or --base] [--check] [--no-browser]
echo Default port: 8000. See README.md for Windows setup.
popd
exit /b 0

:finished
set "RESULT=%errorlevel%"
popd
if not "%RESULT%"=="0" if "%~1"=="" pause
exit /b %RESULT%
