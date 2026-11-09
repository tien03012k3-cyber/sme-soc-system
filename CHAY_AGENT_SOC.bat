@echo off
title SME SOC - KHOI DONG AGENT QUAN TRI (ADMIN)
color 0a

:: 1. Copy sang o C: cuc bo ngay khi con o phien nguoi dung (de khong bi mat o Z khi len Admin)
if not exist "C:\Users\Public\SOC_Agent" mkdir "C:\Users\Public\SOC_Agent" >nul 2>&1
if exist "%~dp0soc_windows_agent.ps1" copy /y "%~dp0soc_windows_agent.ps1" "C:\Users\Public\SOC_Agent\soc_windows_agent.ps1" >nul 2>&1
if exist "Z:\sharemay1\soc_windows_agent.ps1" copy /y "Z:\sharemay1\soc_windows_agent.ps1" "C:\Users\Public\SOC_Agent\soc_windows_agent.ps1" >nul 2>&1
if exist "\\vmware-host\Shared Folders\sharemay1\soc_windows_agent.ps1" copy /y "\\vmware-host\Shared Folders\sharemay1\soc_windows_agent.ps1" "C:\Users\Public\SOC_Agent\soc_windows_agent.ps1" >nul 2>&1
if exist "%~f0" copy /y "%~f0" "C:\Users\Public\SOC_Agent\CHAY_AGENT_SOC.bat" >nul 2>&1

:: 2. Kiem tra quyen Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ======================================================================
    echo       SME SOC - KHOI DONG AGENT MAY TRAM VOI QUYEN ADMIN
    echo ======================================================================
    echo [*] Dang yeu cau quyen Administrator (UAC)...
    echo [*] Vui long bam YES (CO) tren hop thoai UAC de cap quyen cho Agent!
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k C:\Users\Public\SOC_Agent\CHAY_AGENT_SOC.bat' -Verb RunAs"
    exit /b
)

:: 3. Khi da co quyen Administrator tren o dia C:
cd /d "C:\Users\Public\SOC_Agent"
cls
echo ======================================================================
echo       SME SOC - AGENT DANG CHAY VOI QUYEN ADMINISTRATOR!
echo ======================================================================
echo.

:: Bat che do Security Audit de Windows bat buoc phai ghi log Event 4625 khi go sai pass hoac PIN
echo [*] Dang bat Security Audit cho Event ID 4625 (Logon Failure)...
auditpol /set /subcategory:"Logon" /failure:enable /success:enable >nul 2>&1
auditpol /set /subcategory:"Credential Validation" /failure:enable /success:enable >nul 2>&1
auditpol /set /subcategory:"Other Logon/Logoff Events" /failure:enable >nul 2>&1

reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "EnableLinkedConnections" /t REG_DWORD /d 1 /f >nul 2>&1

:: Kiem tra file Agent
if not exist "C:\Users\Public\SOC_Agent\soc_windows_agent.ps1" (
    echo [ERROR] Khong tim thay file soc_windows_agent.ps1!
    echo Vui long dam bao thu muc chia se Z:\sharemay1 co file soc_windows_agent.ps1.
    pause
    exit /b
)

echo [+] Khoi chay PowerShell Agent giam sat thoi gian thuc...
powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Public\SOC_Agent\soc_windows_agent.ps1"

pause
