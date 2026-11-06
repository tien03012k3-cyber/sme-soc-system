@echo off
title SME SOC - Agent May Tram Windows
color 0a

:: 1. Kiem tra quyen Administrator, neu chua co thi tu dong chay voi quyen Admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Dang yeu cau quyen Administrator de quan tri Firewall va Khoa User...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo ======================================================================
echo             SME SOC - DON DEP VA KHOI DONG AGENT CHAY NGAM
echo ======================================================================
echo.

:: 2. Tat tat ca tien trinh Agent va Powershell cu
taskkill /f /im powershell.exe >nul 2>nul
timeout /t 1 /nobreak >nul

:: 3. Don dep sach se thu muc C:\SOC_Agent
if not exist "C:\SOC_Agent" mkdir "C:\SOC_Agent"
del /f /q "C:\SOC_Agent\*.bat" >nul 2>nul
del /f /q "C:\SOC_Agent\*.py" >nul 2>nul
del /f /q "C:\SOC_Agent\*.txt" >nul 2>nul
del /f /q "C:\SOC_Agent\*.tmp" >nul 2>nul

:: 4. Chep dung file Agent Powershell moi nhat vao C:\SOC_Agent
copy /y "%~dp0soc_windows_agent.ps1" "C:\SOC_Agent\soc_windows_agent.ps1" >nul

:: 5. Tao duy nhat 1 file VBS chay ngam
echo Set WshShell = CreateObject("WScript.Shell") > "C:\SOC_Agent\run_silent.vbs"
echo WshShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""C:\SOC_Agent\soc_windows_agent.ps1""", 0, False >> "C:\SOC_Agent\run_silent.vbs"

:: 6. Dang ky tu dong khoi dong duy nhat 1 noi trong Registry Run
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SME_SOC_Agent" /t REG_SZ /d "wscript.exe \"C:\SOC_Agent\run_silent.vbs\"" /f >nul 2>nul

:: Xoa sach trong thu muc Startup neu co
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SME_SOC_Agent.vbs" (
    del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SME_SOC_Agent.vbs" >nul 2>nul
)

:: 7. Khoi dong Agent chay ngam 100% voi quyen Admin
start wscript.exe "C:\SOC_Agent\run_silent.vbs"

echo [+] Da cap nhat code Agent moi nhat vao C:\SOC_Agent!
echo [+] Da cai dat tu dong khoi dong cung Windows moi khi mo may!
echo [+] Tinh nang: Canh ca Desktop + Downloads + Documents + Temp!
echo [+] SOAR: Tu dong tieu huy file doc hai + Chan IP Firewall + Khoa User!
echo.
echo Cua so nay se tu dong dong sau 3 giay...
echo ======================================================================
timeout /t 3 >nul
exit
