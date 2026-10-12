@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (set "PYTHON=python") else (set "PYTHON=py -3")
if not exist .venv\Scripts\python.exe %PYTHON% -m venv .venv
if not exist .venv\Scripts\python.exe (echo 请安装Python 3.10或更新版本。 & pause & exit /b 1)
.venv\Scripts\python.exe -c "import fastapi,uvicorn,multipart" >nul 2>nul
if errorlevel 1 .venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py
if errorlevel 1 pause
