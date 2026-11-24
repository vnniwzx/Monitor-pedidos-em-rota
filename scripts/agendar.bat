@echo off
chcp 65001 >nul
echo Criando tarefas no Agendador do Windows (seg a sex, 21:02 e 22:02)...
schtasks /create /tn "Monitor Em Rota 21h" /tr "\"%~dp0rodar.bat\"" /sc weekly /d MON,TUE,WED,THU,FRI /st 21:02 /f
schtasks /create /tn "Monitor Em Rota 22h" /tr "\"%~dp0rodar.bat\"" /sc weekly /d MON,TUE,WED,THU,FRI /st 22:02 /f
pause
