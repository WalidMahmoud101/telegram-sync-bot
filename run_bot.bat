@echo off
REM run_bot.bat - keeps tg_bot.py alive forever (restarts it on any crash/exit)
cd /d "%~dp0"
:loop
echo [%date% %time%] starting tg_bot.py >> bot_watchdog.log
"%~dp0venv\Scripts\python.exe" "%~dp0tg_bot.py"
echo [%date% %time%] tg_bot.py exited - restarting in 10s >> bot_watchdog.log
timeout /t 10 /nobreak >nul
goto loop
