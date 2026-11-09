@echo off
setlocal EnableDelayedExpansion
title SME SOC - Agent May Tram Windows (Admin Mode)
color 0a

echo ======================================================================
echo       SME SOC - KHOI DONG AGENT QUAN TRI HE THONG (ADMIN MODE)
echo ======================================================================
echo.

:: 1. Tao thu muc C:\SOC_Agent tren o dia cuc bo C:
if not exist "C:\SOC_Agent" mkdir "C:\SOC_Agent"

:: 2. Chep file Agent moi nhat vao C:\SOC_Agent tu moi nguon co the
if exist "%~dp0soc_windows_agent.ps1" (
    copy /y "%~dp0soc_windows_agent.ps1" "C:\SOC_Agent\soc_windows_agent.ps1" >nul 2>&1
)
if exist "Z:\sharemay1\soc_windows_agent.ps1" (
    copy /y "Z:\sharemay1\soc_windows_agent.ps1" "C:\SOC_Agent\soc_windows_agent.ps1" >nul 2>&1
)
if exist "\\vmware-host\Shared Folders\sharemay1\soc_windows_agent.ps1" (
    copy /y "\\vmware-host\Shared Folders\sharemay1\soc_windows_agent.ps1" "C:\SOC_Agent\soc_windows_agent.ps1" >nul 2>&1
)
copy /y "%~f0" "C:\SOC_Agent\CHAY_AGENT_SOC.bat" >nul 2>&1

:: 3. Kiem tra quyen Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Dang yeu cau quyen Administrator (UAC - Hay bam YES/CO tren man hinh)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/c cd /d C:\SOC_Agent && CHAY_AGENT_SOC.bat' -Verb RunAs"
    exit /b
)

:: 4. Xac nhan da o quyen Administrator tren thu muc cuc bo C:\SOC_Agent
cd /d "C:\SOC_Agent"
echo [+] XAC NHAN: Dang chay voi quyen ADMINISTRATOR cao nhat!

:: 5. Bat EnableLinkedConnections de che do Admin van nhin thay o Z:
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "EnableLinkedConnections" /t REG_DWORD /d 1 /f >nul 2>&1

:: 6. Tat cac tien trinh cu va Scheduled Task cu
taskkill /f /im powershell.exe >nul 2>&1
taskkill /f /im wscript.exe >nul 2>&1
timeout /t 1 /nobreak >nul

:: 7. Xoa bo key Run registry cu cua User (tranh chay de 2 phien ban)
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SME_SOC_Agent" /f >nul 2>&1
if exist "C:\SOC_Agent\run_silent.vbs" del /f /q "C:\SOC_Agent\run_silent.vbs" >nul 2>&1

:: 8. Dang ky Scheduled Task chay ngam voi quyen cao nhat khi khoi dong
schtasks /delete /tn "SME_SOC_Agent" /f >nul 2>&1
schtasks /create /tn "SME_SOC_Agent" /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\SOC_Agent\soc_windows_agent.ps1" /sc onlogon /rl HIGHEST /f >nul 2>&1

:: 9. Khoi dong Agent ngay lap tuc
start "SME_SOC_Agent_Console" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\SOC_Agent\soc_windows_agent.ps1"

echo.
echo ======================================================================
echo [+] DA CAI DAT VA KHOI DONG AGENT THANH CONG!
echo [+] Quyen: ADMINISTRATOR (HIGH INTEGRITY)
echo [+] San sang:
echo     - Chuc nang 1: Canh bao Brute-Force (Event ID 4625)
echo     - Chuc nang 2: Tieu huy lo hong CVE tu xa
echo     - Chuc nang 3: SOAR Chan IP Firewall (MITRE M1037)
echo     - Chuc nang 4: SOAR Phong toa User va Khoa ma PIN (MITRE M1036)
echo ======================================================================
echo Cua so nay se tu dong dong sau 3 giay...
timeout /t 3 >nul
exit
