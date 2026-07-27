@echo off
setlocal
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
"%PYTHON_EXE%" -m unittest discover -s "%~dp0tests"
exit /b %errorlevel%
