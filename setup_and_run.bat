@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM 1. Check if Python is installed
REM ============================================================
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed. Please install Python to proceed.
    pause
    exit /b 1
)

REM ============================================================
REM 2. Check if Tesseract OCR is installed; if not, install it
REM ============================================================
set "TESSERACT_EXE=C:\Program Files\Tesseract-OCR\tesseract.exe"
if exist "%TESSERACT_EXE%" (
    echo Tesseract OCR is already installed. Skipping installation.
) else (
    set "TESSERACT_INSTALLER=tesseract-ocr-w64-setup-5.4.0.20240606.exe"
    if not exist "%TESSERACT_INSTALLER%" (
        echo [ERROR] Tesseract setup file "%TESSERACT_INSTALLER%" not found!
        echo Please make sure the installer is in the same directory as this script.
        pause
        exit /b 1
    )

    echo Installing Tesseract OCR...
    "%TESSERACT_INSTALLER%" /SILENT /NORESTART
    if errorlevel 1 (
        echo [ERROR] Tesseract OCR installation failed. Check the installer or your permissions.
        pause
        exit /b 1
    )

    echo Tesseract OCR installed successfully.

    REM Update the PATH for the current session
    set "TESSERACT_DIR=C:\Program Files\Tesseract-OCR"
    set "PATH=%PATH%;%TESSERACT_DIR%"
    echo Updated PATH for current session.

    REM Attempt to persist the updated PATH (may require elevated privileges)
    SETX PATH "%PATH%"
    if errorlevel 1 (
        echo [WARNING] Failed to permanently add Tesseract-OCR to the system PATH.
        echo Please add "%TESSERACT_DIR%" to your PATH manually if necessary.
    ) else (
        echo Tesseract-OCR path added to the system PATH.
    )
)

REM ============================================================
REM 3. Set up the Python virtual environment
REM ============================================================
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo Activating virtual environment...
call venv\Scripts\activate
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment. Verify the 'venv' folder exists.
    pause
    exit /b 1
)

REM ============================================================
REM 4. Upgrade pip and install required packages
REM ============================================================
echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip. Please check your Python and pip installation.
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found. Ensure it is available in the directory.
    pause
    exit /b 1
) else (
    echo Installing required packages from requirements.txt...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install required packages. Check 'requirements.txt' and your internet connection.
        pause
        exit /b 1
    )
)

REM ============================================================
REM 5. Start the Flask application and open it in the browser
REM ============================================================
if not exist "app.py" (
    echo [ERROR] Flask app file 'app.py' not found.
    pause
    exit /b 1
)

echo Starting Flask app...
start "" /b cmd /c "python app.py"
if errorlevel 1 (
    echo [ERROR] Failed to start the Flask app. Please check 'app.py' for errors.
    pause
    exit /b 1
)

REM Give the Flask server a few seconds to start
timeout /t 5 /nobreak >nul

echo Opening Flask app in browser...
start "" "http://127.0.0.1:5000/"

pause
