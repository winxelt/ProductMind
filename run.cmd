@echo off
setlocal
set "PYTHONUTF8=1"
set "PYTHONPATH=%~dp0.local;%PYTHONPATH%"
set "PRODUCTMIND_PYTHON=python"
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "PRODUCTMIND_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%~dp0.venv\Scripts\python.exe" goto ready
"%~dp0.venv\Scripts\python.exe" --version >nul 2>&1
if not errorlevel 1 set "PRODUCTMIND_PYTHON=%~dp0.venv\Scripts\python.exe"
:ready
if "%~1"=="demo" goto demo
if "%~1"=="test" goto test
"%PRODUCTMIND_PYTHON%" -X utf8 "%~dp0productmind.py" %*
exit /b %ERRORLEVEL%
:demo
"%PRODUCTMIND_PYTHON%" -X utf8 "%~dp0demo.py"
exit /b %ERRORLEVEL%
:test
pushd "%~dp0"
"%PRODUCTMIND_PYTHON%" -X utf8 -m unittest discover -s tests -v
set "PRODUCTMIND_RESULT=%ERRORLEVEL%"
popd
exit /b %PRODUCTMIND_RESULT%
