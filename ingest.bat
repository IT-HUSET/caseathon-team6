@echo off
rem Ingests the example policies. Extra args are passed through, e.g.: ingest.bat --limit 2
cd /d "%~dp0"
set "PATH=%PATH%;%USERPROFILE%\.local\bin"
uv run python -m ingest %*
pause
