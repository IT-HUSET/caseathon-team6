@echo off
cd /d "%~dp0"
set "PATH=%PATH%;%USERPROFILE%\.local\bin"
uv run streamlit run app.py
if errorlevel 1 pause
