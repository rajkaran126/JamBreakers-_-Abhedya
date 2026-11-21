@echo off
REM AEGIS-LINK - Windows run script. Creates .venv on first run, then starts the server.
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  py -3.11 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 ( echo Could not create venv. Install Python 3.11+ from python.org & pause & exit /b 1 )
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
  if errorlevel 1 ( echo pip install failed. & pause & exit /b 1 )
)

echo.
echo  AEGIS-LINK starting on http://localhost:8000
echo  Phones on the same Wi-Fi/hotspot: see http://localhost:8000/api/lan
echo  If phones cannot connect: allow Python through Windows Firewall on PRIVATE networks.
echo.
.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
pause
