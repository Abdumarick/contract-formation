@echo off
echo Activating virtual environment...
call .venv\Scripts\activate
echo Starting Hotel Contract Parser...
echo.
echo Please open your web browser and go to: http://localhost:8081
echo.
echo Press Ctrl+C to stop the server
echo.
python web_interface.py
pause
