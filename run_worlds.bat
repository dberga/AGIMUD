@echo off
setlocal enabledelayedexpansion

REM --- Step 0: config ---
set "PREFIX=%~1"
if "%PREFIX%"=="" set "PREFIX=worldsim"

set "NUM_WORLDS=%~2"
if "%NUM_WORLDS%"=="" set "NUM_WORLDS=9"

set "NUM_CHARACTERS=%~3"
if "%NUM_CHARACTERS%"=="" set "NUM_CHARACTERS=8"

set "NUM_EPOCHS=%~4"
if "%NUM_EPOCHS%"=="" set "NUM_EPOCHS=10000"

echo Prefix: %PREFIX% ^| Worlds: %NUM_WORLDS% ^| Characters: %NUM_CHARACTERS% ^| Epochs: %NUM_EPOCHS%

REM --- Step 1: clean folders ---
for /L %%i in (1,1,%NUM_WORLDS%) do (
    set "folder=%PREFIX%%%i"
    if exist "!folder!" (
        echo Removing !folder!
        rmdir /S /Q "!folder!"
    )
)

REM --- Step 2 & 3: launch parallel processes ---
REM Each worker writes a marker file ".done" ONLY if both python steps succeed.
REM On failure, the cmd window stays open (pause) so you can read the error.
for /L %%i in (1,1,%NUM_WORLDS%) do (
    set "folder=%PREFIX%%%i"
    echo Launching !folder!...
    start "!folder!" cmd /C "python swm_generate.py --folder !folder! --characters %NUM_CHARACTERS% && python swm_run.py --world !folder! --max-epoch %NUM_EPOCHS% && echo done > !folder!\.done || (echo FAILED in !folder! & pause)"
)

REM --- Wait for all marker files ---
echo Waiting for all worlds to finish...
:waitloop
set "ALLDONE=1"
for /L %%i in (1,1,%NUM_WORLDS%) do (
    if not exist "%PREFIX%%%i\.done" set "ALLDONE="
)
if not defined ALLDONE (
    timeout /T 3 /NOBREAK >NUL
    goto waitloop
)
echo All worlds finished.

REM --- Step 4: analyze ---
set "WORLDS="
for /L %%i in (1,1,%NUM_WORLDS%) do (
    set "WORLDS=!WORLDS!%PREFIX%%%i,"
)
set "WORLDS=!WORLDS:~0,-1!"

echo Analyzing worlds: !WORLDS!
python swm_analyze.py --worlds "!WORLDS!" --out analysis_%PREFIX%

endlocal