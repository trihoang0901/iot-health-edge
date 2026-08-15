@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title IoT Health Edge - Software Start
set "NO_PAUSE_ARG="
set "FORWARD_ARGS="
:parse_args
if "%~1"=="" goto :run
if /i "%~1"=="--no-pause" (
    set "NO_PAUSE_ARG=-NoPause"
    shift
    goto :parse_args
)
set "FORWARD_ARGS=%FORWARD_ARGS% "%~1""
shift
goto :parse_args
:run
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0IOT-HEALTH-EDGE.ps1" -Action StartSoftware %NO_PAUSE_ARG% %FORWARD_ARGS%
set "FINAL_CODE=%ERRORLEVEL%"
if not defined NO_PAUSE_ARG pause
endlocal & exit /b %FINAL_CODE%
