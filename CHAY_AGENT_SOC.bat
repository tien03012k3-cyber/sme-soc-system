@echo off
title SME SOC - KHOI DONG AGENT QUAN TRI (ADMIN)
color 0a

echo ======================================================================
echo       SME SOC - KHOI DONG AGENT MAY TRAM VOI QUYEN ADMIN
echo ======================================================================
echo.

:: 1. Kiem tra quyen Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Dang yeu cau quyen Administrator (UAC)...
    echo [*] Vui long bam YES (CO) tren man hinh de cap quyen cho Agent!
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

:: 2. Khi da co quyen Administrator
echo [+] XAC NHAN: Dang chay voi quyen ADMINISTRATOR!

:: Tao thu muc C:\SOC_Agent
if not exist "C:\SOC_Agent" mkdir "C:\SOC_Agent"

:: Tim va chep soc_windows_agent.ps1 vao C:\SOC_Agent
set "AGENT_SRC="
if exist "%~dp0soc_windows_agent.ps1" set "AGENT_SRC=%~dp0soc_windows_agent.ps1"
if not defined AGENT_SRC if exist "Z:\sharemay1\soc_windows_agent.ps1" set "AGENT_SRC=Z:\sharemay1\soc_windows_agent.ps1"
if not defined AGENT_SRC if exist "D:\sharemay1\soc_windows_agent.ps1" set "AGENT_SRC=D:\sharemay1\soc_windows_agent.ps1"
if not defined AGENT_SRC if exist "\\vmware-host\Shared Folders\sharemay1\soc_windows_agent.ps1" set "AGENT_SRC=\\vmware-host\Shared Folders\sharemay1\soc_windows_agent.ps1"

if defined AGENT_SRC (
    echo [*] Dang chep Agent tu: %AGENT_SRC%
    copy /y "%AGENT_SRC%" "C:\SOC_Agent\soc_windows_agent.ps1" >nul
) else (
    echo [!] Khong tim thay soc_windows_agent.ps1 o thu muc chia se, kiem tra C:\SOC_Agent...
)

if not exist "C:\SOC_Agent\soc_windows_agent.ps1" (
    echo [ERROR] Khong tim thay file C:\SOC_Agent\soc_windows_agent.ps1!
    echo Vui long dam bao trong thu muc chia se Z:\sharemay1 co file soc_windows_agent.ps1.
    pause
    exit /b
)

:: Bat che do Security Audit de Windows bat buoc phai ghi log Event 4625 khi go sai pass hoac PIN
echo [*] Dang bat Security Audit cho Event ID 4625 (Logon Failure)...
auditpol /set /subcategory:"Logon" /failure:enable /success:enable >nul 2>&1
auditpol /set /subcategory:"Credential Validation" /failure:enable /success:enable >nul 2>&1
auditpol /set /subcategory:"Other Logon/Logoff Events" /failure:enable >nul 2>&1

reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "EnableLinkedConnections" /t REG_DWORD /d 1 /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SME_SOC_Agent" /f >nul 2>&1
schtasks /delete /tn "SME_SOC_Agent" /f >nul 2>&1

echo [+] Dang khoi chay PowerShell Agent...
powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "C:\SOC_Agent\soc_windows_agent.ps1"

pause
