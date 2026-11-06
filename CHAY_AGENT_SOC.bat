@echo off
title SME SOC - Agent May Tram Windows (Admin Mode)
color 0a

:: 1. Kiem tra quyen Administrator, neu chua co thi tu dong yeu cau Run as Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Dang yeu cau quyen Administrator de Agent co the quan tri Firewall va Khoa User...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo ======================================================================
echo       SME SOC - KHOI DONG AGENT VOI QUYEN ADMINISTRATOR CAO NHAT
echo ======================================================================
echo.

:: 2. Tat tat ca tien trinh Agent va Powershell cu
taskkill /f /im powershell.exe >nul 2>nul
timeout /t 1 /nobreak >nul

:: 3. Don dep va tao thu muc C:\SOC_Agent
if not exist "C:\SOC_Agent" mkdir "C:\SOC_Agent"
del /f /q "C:\SOC_Agent\*.bat" >nul 2>nul
del /f /q "C:\SOC_Agent\*.py" >nul 2>nul
del /f /q "C:\SOC_Agent\*.txt" >nul 2>nul
del /f /q "C:\SOC_Agent\*.tmp" >nul 2>nul

:: 4. Chep dung file Agent Powershell moi nhat vao C:\SOC_Agent
copy /y "%~dp0soc_windows_agent.ps1" "C:\SOC_Agent\soc_windows_agent.ps1" >nul

:: 5. Tao Task chay ngam voi quyen Administrator cao nhat (Run with highest privileges)
schtasks /create /tn "SME_SOC_Agent" /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\SOC_Agent\soc_windows_agent.ps1" /sc onlogon /rl HIGHEST /f >nul 2>nul

:: 6. Chay Agent ngay lap tuc voi quyen Administrator
start powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\SOC_Agent\soc_windows_agent.ps1"

echo [+] Da nap Agent ban moi nhat vao C:\SOC_Agent!
echo [+] Da cap quyen ADMINISTRATOR cao nhat cho Agent!
echo [+] Tinh nang: Canh ca Desktop + Downloads + Documents + Temp!
echo [+] SOAR: Tu dong tieu huy CVE + Chan IP Firewall + Phong toa User!
echo.
echo Agent dang am tham hoat dong duoi nen he thong voi quyen Administrator.
echo Cua so nay se tu dong dong sau 3 giay...
echo ======================================================================
timeout /t 3 >nul
exit
