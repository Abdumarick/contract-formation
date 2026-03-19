@echo off
echo Starting Hotel Contract Parser Web Interface...
echo.
echo Please open your web browser and go to: http://localhost:5000
echo.
echo Press Ctrl+C to stop the server
echo.
venv\Scripts\activate

python web_interface.py

pause
