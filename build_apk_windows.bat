@echo off
cd /d "%~dp0"
py -m pip install -U "flet[all]>=0.86,<1" requests phonenumbers
flet build apk
if errorlevel 1 (
    echo BUILD FAILED - read error above.
) else (
    echo Built APK should be in build\apk\
)
pause
