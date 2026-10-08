@echo off
title 11labs CF Automation

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [LOI] Khong tim thay moi truong ao venv!
    echo Vui long kiem tra thu muc venv tai: %~dp0venv
    pause
    exit /b 1
)

if not exist "logs" mkdir "logs"

:: 1. Neu khong co tham so truyen vao (nguoi dung nhap dup chuot) -> Mo Desktop GUI (khong giu cua so CMD)
if "%~1"=="" (
    if exist "%~dp0venv\Scripts\pythonw.exe" (
        start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0main.py"
    ) else (
        start "" "%~dp0venv\Scripts\python.exe" "%~dp0main.py"
    )
    exit /b 0
)

:: 2. Neu tham so la co tuy chon CLI (bat dau bang - hoac /)
set "first_arg=%~1"
if "%first_arg:~0,1%"=="-" (
    "%~dp0venv\Scripts\python.exe" "%~dp0cli.py" %*
    goto :check_error
)
if "%first_arg:~0,1%"=="/" (
    "%~dp0venv\Scripts\python.exe" "%~dp0cli.py" %*
    goto :check_error
)

:: 3. Neu keo tha thu muc vao run.bat
if exist "%~1\*" (
    echo ========================================================
    echo   [CLI] Dang xu ly thu muc: %~1
    echo ========================================================
    "%~dp0venv\Scripts\python.exe" "%~dp0cli.py" -f "%~1"
    echo.
    echo Hoan tat xu ly thu muc.
    pause
    exit /b 0
)

:: 4. Neu keo tha tep .txt vao run.bat
if exist "%~1" (
    echo ========================================================
    echo   [CLI] Dang xu ly tep: %~1
    echo ========================================================
    "%~dp0venv\Scripts\python.exe" "%~dp0cli.py" -i "%~1"
    echo.
    echo Hoan tat xu ly tep.
    pause
    exit /b 0
)

:: 5. Cac truong hop tham so khac
"%~dp0venv\Scripts\python.exe" "%~dp0cli.py" %*

:check_error
if errorlevel 1 (
    echo.
    echo ========================================================
    echo [CANH BAO] Chuong trinh dung lai voi ma loi: %errorlevel%
    echo Vui long kiem tra file nhat ky tai:
    echo   - logs\crash.log
    echo   - logs\error_*.log
    echo   - logs\app_*.log
    echo ========================================================
    pause
)
