@echo off
chcp 65001 >nul
cd /d "%~dp0.."
rem Sobe o TMS simulado em http://127.0.0.1:8000 (deixe esta janela aberta)
".venv\Scripts\python.exe" demo\servidor_simulado.py
pause
