@echo off
cd /d %~dp0\..
call .venv\Scripts\activate.bat
pyinstaller --noconfirm --clean packaging\mineru_batch.spec --distpath dist --workpath build
if errorlevel 1 (echo BUILD FAILED & exit /b 1)
echo OK: dist\ES MinerU Batch.exe
