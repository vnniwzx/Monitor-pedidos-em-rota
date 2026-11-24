@echo off
rem Usado pelo Agendador de Tarefas do Windows (navegador invisivel)
cd /d "%~dp0.."
".venv\Scripts\python.exe" monitor_em_rota.py
