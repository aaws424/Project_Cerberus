@echo off
rem ============================================================================
rem  Project Cerberus - run
rem  Builds the environment if needed, then opens the admin console in your browser.
rem
rem    run.bat          open the admin console (Arabic, with an English toggle)
rem    run.bat batch    process the seed tickets in this window and print the run report
rem    run.bat eval     print the evaluation on the seed set
rem
rem  Stop the console with Ctrl+C in this window.
rem  Set CERBERUS_NO_BROWSER=1 to start the server without opening a browser.
rem ============================================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set VENV_PY=.venv\Scripts\python.exe

call "%~dp0build.bat" quick || exit /b 1

if /i "%~1"=="batch" goto batch
if /i "%~1"=="eval" goto eval

rem --- pick a free port, starting at 8501 ---------------------------------------
set PORT=8501
:find_port
netstat -ano | findstr /r /c:":%PORT%  *.*LISTENING" >nul && set /a PORT+=1 && goto find_port

echo.
echo   Cerberus admin console:  http://localhost:%PORT%
echo   Press Ctrl+C in this window to stop it.
echo.
if not defined CERBERUS_NO_BROWSER start "" /b "%VENV_PY%" -c "import time, webbrowser; time.sleep(4); webbrowser.open('http://localhost:%PORT%')"
"%VENV_PY%" -m streamlit run app\streamlit_app.py --server.port %PORT%
exit /b %errorlevel%

:batch
"%VENV_PY%" -m cerberus run --reset --as-of-last
pause
exit /b 0

:eval
"%VENV_PY%" -m cerberus eval
pause
exit /b 0
