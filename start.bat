@echo off
REM MediaBot - Docker'siz ishga tushirish (Windows)
setlocal
cd /d "%~dp0"
chcp 65001 >nul

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>nul
if errorlevel 1 (
  echo [X] Python 3.12+ topilmadi. O'rnating: https://www.python.org/downloads/  ^(Add to PATH belgisini qo'ying^)
  pause & exit /b 1
)
where ffmpeg >nul 2>nul || (
  echo [X] ffmpeg topilmadi. O'rnating: winget install Gyan.FFmpeg  yoki  https://ffmpeg.org/download.html
  pause & exit /b 1
)
where deno >nul 2>nul || echo [!] deno topilmadi - YouTube'dagi ba'zi formatlar chiqmasligi mumkin. O'rnatish: winget install DenoLand.Deno

if not exist .env (
  copy .env.example .env >nul
  echo [i] .env fayli yaratildi. Uni Bloknot bilan oching, BOT_TOKEN ni yozing va start.bat ni qayta ishga tushiring.
  pause & exit /b 0
)

if not exist .venv (
  echo [i] Virtual muhit yaratilmoqda...
  %PY% -m venv .venv || (pause & exit /b 1)
)
call .venv\Scripts\activate.bat
if not exist .venv\.installed (
  echo [i] Kutubxonalar o'rnatilmoqda ^(bir marta^)...
  python -m pip install --upgrade pip >nul
  python -m pip install -r requirements.txt -c requirements.lock || (pause & exit /b 1)
  type nul > .venv\.installed
)

if not exist data\downloads mkdir data\downloads
echo [>] Bot ishga tushdi. To'xtatish: Ctrl+C
python -m bot.main
pause
