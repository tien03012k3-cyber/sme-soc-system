@echo off
title SME SOC - KHOI DONG AGENT QUAN TRI (ADMIN)
color 0a

echo ======================================================================
echo       SME SOC - KHOI DONG AGENT MAY TRAM VOI QUYEN ADMIN
echo ======================================================================
echo.

:: 1. Tao thu muc C:\SOC_Agent tren o dia cuc bo C:
if not exist "C:\SOC_Agent" mkdir "C:\SOC_Agent"

:: 2. Chep file Agent vao C:\SOC_Agent tu thu muc hien tai
if exist "%~dp0soc_windows_agent.ps1" copy /y "%~dp0soc_windows_agent.ps1" "C:\SOC_Agent\soc_windows_agent.ps1" >nul 2>&1
if exist "Z:\sharemay1\soc_windows_agent.ps1" copy /y "Z:\sharemay1\soc_windows_agent.ps1" "C:\SOC_Agent\soc_windows_agent.ps1" >nul 2>&1
if exist "\\vmware-host\Shared Folders\sharemay1\soc_windows_agent.ps1" copy /y "\\vmware-host\Shared Folders\sharemay1\soc_windows_agent.ps1" "C:\SOC_Agent\soc_windows_agent.ps1" >nul 2>&1
copy /y "%~f0" "C:\SOC_Agent\CHAY_AGENT_SOC.bat" >nul 2>&1

:: 3. Kiem tra quyen Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Dang yeu cau quyen Administrator (UAC)...
    echo [*] Vui long bam YES (CO) tren man hinh de cap quyen cho Agent!
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File C:\SOC_Agent\soc_windows_agent.ps1' -Verb RunAs"
    exit /b
)

:: 4. Neu da co quyen Administrator (vi du khi click phai chon Run as administrator)
echo [+] XAC NHAN: Dang chay voi quyen ADMINISTRATOR!
taskkill /f /im powershell.exe >nul 2>&1
taskkill /f /im wscript.exe >nul 2>&1
timeout /t 1 /nobreak >nul

:: Bat buoc Windows phai ghi log Event 4625 khi go sai pass hoac PIN
auditpol /set /subcategory:"Logon" /failure:enable /success:enable >nul 2>&1
auditpol /set /subcategory:"Credential Validation" /failure:enable /success:enable >nul 2>&1
auditpol /set /subcategory:"Other Logon/Logoff Events" /failure:enable >nul 2>&1

reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "EnableLinkedConnections" /t REG_DWORD /d 1 /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SME_SOC_Agent" /f >nul 2>&1
schtasks /delete /tn "SME_SOC_Agent" /f >nul 2>&1

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\SOC_Agent\soc_windows_agent.ps1"
