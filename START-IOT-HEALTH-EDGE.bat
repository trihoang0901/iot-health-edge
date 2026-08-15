@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "ROOT=%~dp0"
set "LAUNCHER=%ROOT%scripts\Start-IotHealthEdge.ps1"

if not exist "%LAUNCHER%" (
    echo [ERROR] Khong tim thay launcher PowerShell: "%LAUNCHER%"
    endlocal & exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" %*
set "FINAL_CODE=%ERRORLEVEL%"
endlocal & exit /b %FINAL_CODE%
