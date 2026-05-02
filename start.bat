@echo off
setlocal

cd /d "%~dp0"

if "%HOST%"=="" set HOST=127.0.0.1
if "%PORT%"=="" set PORT=8000
if "%VENV_DIR%"=="" set VENV_DIR=.venv

where uv >nul 2>nul
if %errorlevel%==0 (
  if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [start] creating virtualenv with uv
    uv venv --python 3.12 "%VENV_DIR%"
    if errorlevel 1 goto :error
  )
  echo [start] syncing dependencies with uv
  uv sync --extra test
  if errorlevel 1 goto :error
  echo [start] starting http://%HOST%:%PORT%
  uv run uvicorn app.main:app --host %HOST% --port %PORT% --reload
  goto :end
)

where py >nul 2>nul
if %errorlevel%==0 (
  set PYTHON_CMD=py -3.12
) else (
  set PYTHON_CMD=python
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo [start] creating virtualenv with Python
  %PYTHON_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 goto :python_error
)

echo [start] installing dependencies with pip
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
"%VENV_DIR%\Scripts\python.exe" -m pip install -e ".[test]"
if errorlevel 1 goto :error

echo [start] starting http://%HOST%:%PORT%
"%VENV_DIR%\Scripts\python.exe" -m uvicorn app.main:app --host %HOST% --port %PORT% --reload
goto :end

:python_error
echo [start] Python 3.12 이상 또는 uv가 필요합니다.
echo [start] uv 설치: https://docs.astral.sh/uv/
exit /b 1

:error
echo [start] 실행 중 오류가 발생했습니다.
exit /b 1

:end
endlocal
