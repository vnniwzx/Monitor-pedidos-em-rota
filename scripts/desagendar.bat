@echo off
chcp 65001 >nul
schtasks /delete /tn "Monitor Em Rota 21h" /f
schtasks /delete /tn "Monitor Em Rota 22h" /f
pause
