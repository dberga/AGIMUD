@echo off
setlocal enabledelayedexpansion

REM --- Step 0: config ---
set "PREFIX=%~1"
if "%PREFIX%"=="" set "PREFIX=worldsim"

set "NUM_WORLDS=%~2"
if "%NUM_WORLDS%"=="" set "NUM_WORLDS=9"

set "NUM_CHARACTERS=%~3"
if "%NUM_CHARACTERS%"=="" set "NUM_CHARACTERS=8"

echo Prefix: %PREFIX% ^| Worlds: %NUM_WORLDS% ^| Characters: %NUM_CHARACTERS%

REM --- Step 1: clean folders ---
for /L %%i in (1,1,%NUM_WORLDS%) do (
    set "folder=%PREFIX%%%i"
    if exist "!folder!" (
        echo Removing !folder!
        rmdir /S /Q "!folder!"
    )
)

REM --- Step 2 & 3: launch parallel processes ---
for /L %%i in (1,1,%NUM_WORLDS%) do (
    set "folder=%PREFIX%%%i"
    echo Launching !folder!...
    start "!folder!" cmd /C "python swm_generate.py --folder !folder! --characters %NUM_CHARACTERS% && python swm_run.py --folder !folder!"
)

REM --- Wait for all "worldsim*" windows to finish ---
echo Waiting for all worlds to finish...
:waitloop
tasklist /FI "WINDOWTITLE eq %PREFIX%*" 2>NUL | find /I "%PREFIX%" >NUL
if not errorlevel 1 (
    timeout /T 3 /NOBREAK >NUL
    goto waitloop
)

REM --- Step 4: analyze ---
set "WORLDS="
for /L %%i in (1,1,%NUM_WORLDS%) do (
    set "WORLDS=!WORLDS!%PREFIX%%%i,"
)
set "WORLDS=!WORLDS:~0,-1!"

echo Analyzing worlds: !WORLDS!
python swm_analyze.py --worlds "!WORLDS!"

endlocal