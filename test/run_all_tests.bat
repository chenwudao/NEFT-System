@echo off
echo =========================================
echo Running NEFT Test Suite
echo =========================================

REM Add the project root to PYTHONPATH so imports work correctly
set PYTHONPATH=%~dp0..

REM Run pytest on the test directory
cd /d "%~dp0"
python -m pytest . -v

echo =========================================
pause
