@echo off
echo Activating virtual environment...
call .venv\Scripts\activate
echo Starting Hotel Contract Parser...
echo.
if "%APP_USERNAME%"=="" set /p APP_USERNAME=Office username:
if "%APP_PASSWORD%"=="" set /p APP_PASSWORD=Office password:
if "%APP_USERNAME%"=="" (
  echo ERROR: A username is required.
  exit /b 1
)
if "%APP_PASSWORD%"=="" (
  echo ERROR: A password is required.
  exit /b 1
)
echo Open http://SERVER-IP:8081 from an office computer.
echo.
echo Press Ctrl+C to stop the server
echo.
python -m waitress --host=0.0.0.0 --port=8081 --threads=4 web_interface:app
pause
