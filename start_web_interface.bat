@echo off
echo Starting Hotel Contract Parser Web Interface...
echo.
echo Please open your web browser and go to: http://localhost:8081
echo.
echo Press Ctrl+C to stop the server
echo.
call .venv\Scripts\activate

python web_interface.py

pause
