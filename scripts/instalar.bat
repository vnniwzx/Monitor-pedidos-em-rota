@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo === Instalando o Monitor de Pedidos Em Rota ===

rem Testa se o Python funciona de verdade (o atalho da Microsoft Store da erro)
set "PY="
py --version >nul 2>nul && set "PY=py"
if not defined PY (
  python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python nao encontrado. Instale pelo python.org e marque "Add python.exe to PATH".
  pause
  exit /b 1
)

echo [1/4] Criando ambiente virtual...
%PY% -m venv .venv || goto erro
echo [2/4] Instalando bibliotecas...
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt || goto erro
echo [3/4] Baixando o navegador do Playwright...
".venv\Scripts\python.exe" -m playwright install chromium || goto erro
echo [4/4] Criando config.ini...
if not exist config.ini copy config.exemplo.ini config.ini >nul

echo.
echo Pronto! Para a demonstracao: rode scripts\iniciar_demo.bat
pause
exit /b 0

:erro
echo Deu erro na instalacao.
pause
exit /b 1
