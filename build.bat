@echo off
rem ============================================================================
rem  Project Cerberus - build
rem  Creates a private Python environment in .venv and installs what the app needs.
rem
rem    build.bat          build (or update) the environment, then run the tests
rem    build.bat quick    build only, skip the tests (run.bat uses this)
rem    build.bat clean    delete .venv and build again from scratch
rem
rem  Note: no parenthesised IF blocks below, because this folder's name contains
rem  parentheses, which would break them.
rem ============================================================================
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set VENV_PY=.venv\Scripts\python.exe

if /i "%~1"=="clean" if exist .venv echo Deleting .venv ...
if /i "%~1"=="clean" if exist .venv rmdir /s /q .venv

rem --- 1. Python environment -------------------------------------------------
if not exist "%VENV_PY%" goto make_venv
"%VENV_PY%" -c "import sys" >nul 2>&1 && goto have_venv
echo The .venv folder is broken. Rebuilding it ...
rmdir /s /q .venv

:make_venv
call :find_python || goto fail
echo Creating the Python environment in .venv with: %PY_CMD%
%PY_CMD% -m venv .venv || goto fail
if exist .venv\requirements.installed del .venv\requirements.installed

:have_venv
rem --- 2. Packages (reinstalled only when requirements.txt changes) ------------
fc /b requirements.txt .venv\requirements.installed >nul 2>&1 && goto deps_ok
echo Installing packages. The first time this takes a few minutes ...
"%VENV_PY%" -m pip install --upgrade pip >nul 2>&1
"%VENV_PY%" -m pip install -r requirements.txt || goto fail
copy /y requirements.txt .venv\requirements.installed >nul
:deps_ok
echo Environment ready: .venv

rem --- 3. Tests -----------------------------------------------------------------
if /i "%~1"=="quick" exit /b 0
echo Running the tests ...
"%VENV_PY%" -m pytest -q || goto fail
echo.
echo   BUILD OK. Start the app with run.bat
echo.
pause
exit /b 0

:fail
echo.
echo   BUILD FAILED. Read the messages above.
echo.
pause
exit /b 1

rem --- find Python 3.10 or newer ------------------------------------------------
:find_python
set PY_CMD=
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY_CMD=py -3" && exit /b 0
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY_CMD=python" && exit /b 0
echo.
echo   Python 3.10 or newer was not found.
echo   Install it from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during the installation.
exit /b 1
