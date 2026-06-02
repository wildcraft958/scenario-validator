@echo off
REM setup.bat -- Install dependencies for the EuroNCAP Scenario Validator (Windows)
REM
REM Security design:
REM   - Never downloads uv. If uv is already installed by IT/CI, it is used for speed.
REM   - Falls back to standard pip with pinned versions.
REM   - Use --hashed flag to enforce cryptographic hash verification.
REM
REM Usage:
REM   setup.bat            (standard install)
REM   setup.bat --hashed   (enforce hash verification -- Linux x86_64 only)

setlocal

set SCRIPT_DIR=%~dp0
set PLAIN_LOCK=%SCRIPT_DIR%requirements-lock.txt
set HASHED_LOCK=%SCRIPT_DIR%requirements-hashed.txt
set USE_HASHES=0
set REQ_FILE=%PLAIN_LOCK%

for %%A in (%*) do (
    if "%%A"=="--hashed" set USE_HASHES=1
)

if "%USE_HASHES%"=="1" (
    set REQ_FILE=%HASHED_LOCK%
    echo Mode: hash-verified ^(pip --require-hashes^)
) else (
    echo Mode: pinned versions ^(pip^)
)

echo EuroNCAP Validator -- dependency install
echo =========================================

where uv >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=*" %%v in ('uv --version 2^>nul') do echo Tool: uv %%v
    if "%USE_HASHES%"=="1" (
        uv pip install --system --require-hashes -r "%REQ_FILE%"
    ) else (
        uv pip install --system -r "%REQ_FILE%"
    )
) else (
    echo Tool: pip ^(uv not found on PATH -- using standard Python tools^)
    python -m pip install --upgrade pip --quiet
    if "%USE_HASHES%"=="1" (
        python -m pip install --require-hashes -r "%REQ_FILE%"
    ) else (
        python -m pip install -r "%REQ_FILE%"
    )
)

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Done. Run: python validator.py ^<scenario_dir^>
) else (
    echo.
    echo ERROR: Installation failed. Check the error above.
    exit /b 1
)

endlocal
