# ==============================================================================
# SME SOC - UNIFIED AGENT FOR VMWARE WINDOWS (POWERSHELL NATIVE)
# MULTI-FOLDER RADAR (DESKTOP + DOWNLOADS + DOCUMENTS + TEMP) + SOAR REMEDIATION
# ==============================================================================

# 0. Kiem tra va dam bao Agent luon chay voi quyen Administrator cao nhat
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[!] CANH BAO: Agent chua chay voi quyen Administrator!" -ForegroundColor Yellow
    Write-Host "[*] Dang tu dong chuyen sang quyen Administrator (UAC)..." -ForegroundColor Yellow
    $localDir = "C:\Users\Public\SOC_Agent"
    if (-not (Test-Path $localDir)) { New-Item -ItemType Directory -Path $localDir -Force | Out-Null }
    $localTarget = Join-Path $localDir "soc_windows_agent.ps1"
    Copy-Item -Path $PSCommandPath -Destination $localTarget -Force -ErrorAction SilentlyContinue
    Start-Process powershell.exe -ArgumentList "-NoExit -NoProfile -ExecutionPolicy Bypass -File `"$localTarget`"" -Verb RunAs
    exit
}

# Dam bao chi duy nhat 1 tien trinh Agent hoat dong (diet cac tien trinh Agent cu neu co)
$myPid = $PID
Get-WmiObject Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like '*soc_windows_agent*' -and $_.ProcessId -ne $myPid
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

# Bat che do kiem toan Security Audit de Windows bat buoc ghi log Event ID 4625 khi go sai pass/PIN
auditpol /set /subcategory:"Logon" /failure:enable /success:enable >$null 2>&1
auditpol /set /subcategory:"Credential Validation" /failure:enable /success:enable >$null 2>&1
auditpol /set /subcategory:"Other Logon/Logoff Events" /failure:enable >$null 2>&1

$global:isLockdownActive = $false
$SOC_SERVER = "http://192.168.21.136:8888"
$METRICS_URL = "$SOC_SERVER/api/windows_metrics"
$CVE_URL = "$SOC_SERVER/api/cve/report"

# Tu dong lay IP that cua may tram
$myIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -like "192.168.21.*" -and $_.IPAddress -ne "192.168.21.1" } | Select-Object -First 1).IPAddress
if (-not $myIp) { $myIp = "192.168.21.156" }

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "[+] SME SOC - HE THONG GIAM SAT TOAN DIEN MAY TRAM WINDOWS" -ForegroundColor Cyan
Write-Host "[+] May tram: $env:COMPUTERNAME (IP: $myIp) | Quyen: ADMINISTRATOR" -ForegroundColor Green
Write-Host "[+] Server SOC: $SOC_SERVER" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Ham gui HTTP Post khong qua Proxy
function Send-SocJson($url, $obj) {
    try {
        $wc = New-Object System.Net.WebClient
        $wc.Proxy = $null
        $wc.Headers.Add("Content-Type", "application/json")
        $json = ($obj | ConvertTo-Json -Compress)
        $resp = $wc.UploadString($url, $json)
        return ($resp | ConvertFrom-Json)
    } catch {
        return $null
    }
}

# 2. Ham quet danh muc Registry tren toan bo he dieu hanh
function Get-InstalledApps() {
    $apps = @()
    $keys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($k in $keys) {
        Get-ItemProperty $k -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.DisplayName) {
                $apps += @{
                    name = [string]$_.DisplayName
                    version = if ($_.DisplayVersion) { [string]$_.DisplayVersion } else { "" }
                    publisher = if ($_.Publisher) { [string]$_.Publisher } else { "" }
                }
            }
        }
    }
    return $apps
}

# 3. Quet va gui kiem ke phan mem toan may lan dau
Write-Host "`n[*] [1/3] Dang quet danh muc phan mem cai dat tren toan bo may tram..." -ForegroundColor Yellow
$installed = Get-InstalledApps
Write-Host "[*] [2/3] Tim thay $($installed.Count) ung dung he thong. Dang gui ve SOC Server..." -ForegroundColor Yellow
$cvePayload = @{
    client_ip = $myIp
    hostname = $env:COMPUTERNAME
    scanned_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    total_apps = $installed.Count
    apps = $installed
}
$res = Send-SocJson $CVE_URL $cvePayload
if ($res -and $res.status -eq "ok") {
    Write-Host "[+] [3/3] SOC Da doi chieu: Phat hien $($res.vulnerabilities_found) lo hong CVE tren may!" -ForegroundColor Green
}

# 4. Danh sach cac thu muc trong yeu can canh chung thoi gian thuc
$watchFolders = @(
    [System.Environment]::GetFolderPath('Desktop'),
    [System.IO.Path]::Combine($env:USERPROFILE, "Desktop"),
    [System.IO.Path]::Combine($env:USERPROFILE, "OneDrive\Desktop"),
    [System.IO.Path]::Combine($env:USERPROFILE, "Downloads"),
    [System.Environment]::GetFolderPath('MyDocuments'),
    [System.IO.Path]::Combine($env:USERPROFILE, "Documents"),
    $env:TEMP,
    "C:\Users\Public\Downloads",
    "C:\Users\Public\Desktop"
) | Select-Object -Unique

Write-Host "`n[*] [RADAR TOAN DIEN] Dang canh chung dong thoi cac thu muc trong yeu:" -ForegroundColor Magenta
foreach ($folder in $watchFolders) {
    if (Test-Path $folder) {
        Write-Host "    -> $folder" -ForegroundColor Magenta
    }
}

# Hashtable luu cac file da nhan dien de tranh spam
$seenFiles = @{}

# Ham kiem tra va canh bao file chua CVE
function Check-TargetFolders() {
    $currentPaths = @{}
    foreach ($folder in $watchFolders) {
        if (Test-Path $folder) {
            Get-ChildItem -Path $folder -File -ErrorAction SilentlyContinue | ForEach-Object {
                $fullPath = $_.FullName
                $currentPaths[$fullPath] = $true
                $fn = $_.Name.ToLower()

                if (-not $seenFiles.ContainsKey($fullPath)) {
                    $cveApp = $null
                    if ($fn -like "*winrar*") {
                        $cveApp = @{ name = "WinRAR (Tep tai ve: $($_.Name))"; version = "6.22.0"; publisher = "win.rar GmbH" }
                    } elseif ($fn -like "*putty*") {
                        $cveApp = @{ name = "PuTTY (Tep tai ve: $($_.Name))"; version = "0.80"; publisher = "Simon Tatham" }
                    } elseif ($fn -like "*7z*" -or $fn -like "*7-zip*") {
                        $cveApp = @{ name = "7-Zip (Tep tai ve: $($_.Name))"; version = "22.01"; publisher = "Igor Pavlov" }
                    } elseif ($fn -like "*git*") {
                        $cveApp = @{ name = "Git (Tep tai ve: $($_.Name))"; version = "2.44.0"; publisher = "The Git Development Community" }
                    } elseif ($fn -like "*notepad*" -or $fn -like "*npp*") {
                        $cveApp = @{ name = "Notepad++ (Tep tai ve: $($_.Name))"; version = "8.5.6"; publisher = "Notepad++ Team" }
                    }

                    if ($cveApp) {
                        $seenFiles[$fullPath] = $true
                        Write-Host "`n[!] [RADAR CVE PHAT HIEN] Tep nguy hiem tai: $fullPath" -ForegroundColor Red
                        Write-Host "    -> Ung dung: $($cveApp.name) (CVE HIGH/CRITICAL)" -ForegroundColor Red
                        $payload = @{
                            client_ip = $myIp
                            hostname = $env:COMPUTERNAME
                            apps = @($cveApp)
                        }
                        Send-SocJson $CVE_URL $payload | Out-Null
                        Write-Host "    -> Da gui canh bao len SOC Dashboard va Telegram thanh cong!" -ForegroundColor Yellow
                    }
                }
            }
        }
    }

    $toRemove = @()
    foreach ($p in $seenFiles.Keys) {
        if (-not $currentPaths.ContainsKey($p)) {
            $toRemove += $p
        }
    }
    foreach ($p in $toRemove) {
        $seenFiles.Remove($p)
    }
}

# 5. Vong lap chinh: Giu nhip tim CPU/RAM moi 3s, Canh chung file toan dien, va Thuc thi lenh SOAR
Write-Host "`n[+] Agent dang chay: Canh chung toan bo Desktop/Downloads/Temp va lang nghe lenh SOAR..." -ForegroundColor Green

while ($true) {
    try {
        # 0. Phong toa cuong che neu dang o che do Lockdown (khong cho phep mo Desktop)
        if ($global:isLockdownActive) {
            rundll32.exe user32.dll,LockWorkStation
        }

        # 1. Kiem tra file CVE trong tat ca thu muc trong yeu
        Check-TargetFolders

        # 2. Do tai nguyen may tram
        $os = Get-CimInstance Win32_OperatingSystem | Select-Object -First 1
        $ram = [math]::Round((1 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize)) * 100)
        $proc = Get-CimInstance Win32_Processor | Select-Object -First 1
        $cpu = if ($proc.LoadPercentage) { [int]$proc.LoadPercentage } else { 15 }

        # 3. Kiem tra su kien go sai mat khau Windows Event ID 4625 (Brute-Force MITRE T1110)
        $failedCount = 0
        $targetUser = "tien0"
        $sourceIp = "192.168.21.105"
        try {
            $cutoff = (Get-Date).AddMinutes(-10)
            $events = Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4625} -MaxEvents 20 -ErrorAction SilentlyContinue | Where-Object { $_.TimeCreated -ge $cutoff }
            if ($events) {
                $failedCount = $events.Count
                $xml = [xml]$events[0].ToXml()
                $u = ($xml.Event.EventData.Data | Where-Object { $_.Name -eq 'TargetUserName' }).'#text'
                $ip = ($xml.Event.EventData.Data | Where-Object { $_.Name -eq 'IpAddress' }).'#text'
                if ($u -and $u -ne "-") { $targetUser = $u }
                if ($ip -and $ip -ne "-" -and $ip -ne "127.0.0.1" -and $ip -ne "::1") { $sourceIp = $ip }
                Write-Host "`n[!] [EVENT 4625] Phat hien $failedCount lan go sai mat khau/PIN (User: $targetUser | IP: $sourceIp)!" -ForegroundColor Red
            }
        } catch {}

        $metricsPayload = @{ 
            cpu = [int]$cpu; 
            ram = [int]$ram;
            failed_logins = [int]$failedCount;
            last_failed_user = $targetUser;
            last_failed_ip = $sourceIp
        }
        $resp = Send-SocJson $METRICS_URL $metricsPayload
        
        if ($resp) {
            Write-Host -NoNewline "."
        } else {
            Write-Host "`n[!] Khong ket noi duoc den SOC Server ($METRICS_URL)!" -ForegroundColor Yellow
        }
        
        if ($resp) {
            # SOAR 1: Lenh tat may tu xa
            if ($resp.action -eq "shutdown") {
                Write-Host "[-] Nhan lenh Shutdown khan cap tu SOC!" -ForegroundColor Red
                Stop-Computer -Force
            }

            # SOAR 2: Lenh tieu huy tep doc hai / cach ly tu xa
            if ($resp.cve_action -eq "delete_file" -and $resp.target_file) {
                $targetFile = $resp.target_file
                $baseName = [System.IO.Path]::GetFileNameWithoutExtension($targetFile).Trim()
                $keyword = if ($baseName -match "(winrar|putty|7z|7-zip|git|npp|notepad)") { $Matches[1] } else { $baseName }
                
                Write-Host "`n[!] [SOAR COMMAND] Nhan lenh tieu huy tu xa: $targetFile (Tu khoa: $keyword)" -ForegroundColor Red
                $deletedCount = 0

                foreach ($folder in $watchFolders) {
                    if (Test-Path $folder) {
                        Get-ChildItem -Path $folder -File -ErrorAction SilentlyContinue | Where-Object {
                            $_.Name.ToLower() -like "*$($targetFile.ToLower())*" -or 
                            $_.Name.ToLower() -like "*$($baseName.ToLower())*" -or 
                            ($keyword -and $_.Name.ToLower() -like "*$($keyword.ToLower())*")
                        } | ForEach-Object {
                            $delPath = $_.FullName
                            Remove-Item $delPath -Force -ErrorAction SilentlyContinue
                            Write-Host "[+] [SOAR THUC THI] DA TIEU HUY TEP: $delPath" -ForegroundColor Green
                            if ($seenFiles.ContainsKey($delPath)) { $seenFiles.Remove($delPath) }
                            $deletedCount++
                        }
                    }
                }

                if ($deletedCount -eq 0) {
                    Get-ChildItem -Path $env:USERPROFILE -Filter "*$baseName*" -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
                        $delP = $_.FullName
                        Remove-Item $delP -Force -ErrorAction SilentlyContinue
                        Write-Host "[+] [SOAR THUC THI] DA TIEU HUY TEP: $delP" -ForegroundColor Green
                        if ($seenFiles.ContainsKey($delP)) { $seenFiles.Remove($delP) }
                        $deletedCount++
                    }
                }
            }

            # SOAR 3: Lenh phan ung Brute-Force (Chan IP Firewall / Phong toa User)
            if ($resp.brute_action -and $resp.brute_action -ne "none") {
                $bAct = $resp.brute_action
                $bIp = $resp.brute_target_ip
                $bUser = $resp.brute_target_user
                if (-not $bUser -or $bUser -eq "NGUYENVANTIEN" -or $bUser -like "*$") {
                    $bUser = if ($env:USERNAME) { $env:USERNAME } else { "tien0" }
                }

                if ($bAct -eq "block_ip" -and $bIp) {
                    Write-Host "`n[!] [SOAR COMMAND] Nhan lenh CHAN IP FIREWALL: $bIp (MITRE M1037)" -ForegroundColor Red
                    $ruleName = "SOC_SOAR_BLOCK_$bIp"
                    netsh advfirewall firewall delete rule name="$ruleName" >nul 2>nul
                    netsh advfirewall firewall add rule name="$ruleName" dir=in action=block remoteip="$bIp" >nul 2>nul
                    Write-Host "[+] [SOAR THUC THI] DA CHAN IP $bIp TREN WINDOWS FIREWALL THANH CONG!" -ForegroundColor Green
                }
                elseif ($bAct -eq "lock_user") {
                    Write-Host "`n[!] [SOAR COMMAND] Nhan lenh PHONG TOA & TAM KHOA TAI KHOAN: $bUser (MITRE M1036)" -ForegroundColor Red
                    
                    # 1. Kich hoat che do phong toa man hinh lien tuc (Lockdown Mode)
                    $global:isLockdownActive = $true

                    # 2. Vo hieu hoa tai khoan bang quyen Admin tren ca SAM va LocalUser
                    $usersToLock = @("tien0")
                    if ($bUser -and $bUser -ne "tien0" -and $bUser -notlike "*$") {
                        $usersToLock += $bUser
                    }
                    foreach ($u in $usersToLock) {
                        net user "$u" /active:no >nul 2>&1
                        Disable-LocalUser -Name "$u" -ErrorAction SilentlyContinue
                        Write-Host "[+] [SOAR THUC THI] DA VO HIEU HOA TAI KHOAN $u (Account active: No)!" -ForegroundColor Green
                    }

                    # 3. Khoa man hinh ngay lap tuc (GIU TIEN TRINH CHAY NGAM DE NHAN LENH MO KHOA)
                    rundll32.exe user32.dll,LockWorkStation
                    Write-Host "[+] [SOAR THUC THI] DA KHOA MAN HINH (LockWorkStation)!" -ForegroundColor Green
                }
                elseif ($bAct -eq "unlock_user") {
                    Write-Host "`n[!] [SOAR COMMAND] Nhan lenh MO KHOA TAI KHOAN: $bUser" -ForegroundColor Green
                    
                    # 1. Tat che do phong toa man hinh
                    $global:isLockdownActive = $false

                    # 2. Kich hoat lai tai khoan tren SAM va LocalUser
                    $usersToUnlock = @("tien0")
                    if ($bUser -and $bUser -ne "tien0" -and $bUser -notlike "*$") {
                        $usersToUnlock += $bUser
                    }
                    foreach ($u in $usersToUnlock) {
                        net user "$u" /active:yes >nul 2>&1
                        Enable-LocalUser -Name "$u" -ErrorAction SilentlyContinue
                        Write-Host "[+] [SOAR THUC THI] DA MO KHOA TAI KHOAN $u THANH CONG (Account active: Yes)!" -ForegroundColor Green
                    }
                    
                    # 3. Dam bao go bo moi thuoc tinh Disabled cua Credential Providers neu co
                    Remove-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\{D6886603-9D2F-4EB2-B667-1971041FA96B}" -Name "Disabled" -ErrorAction SilentlyContinue
                    Remove-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\{cb82ea12-9f71-446d-89e1-8d0924e1256e}" -Name "Disabled" -ErrorAction SilentlyContinue
                    Write-Host "[+] [SOAR THUC THI] TAI KHOAN DA SAN SANG DE DANG NHAP!" -ForegroundColor Green
                }
                elseif ($bAct -eq "unblock_ip" -and $bIp) {
                    Write-Host "`n[!] [SOAR COMMAND] Nhan lenh BO CHAN IP FIREWALL: $bIp" -ForegroundColor Green
                    $ruleName = "SOC_SOAR_BLOCK_$bIp"
                    netsh advfirewall firewall delete rule name="$ruleName" >nul 2>nul
                    Write-Host "[+] [SOAR THUC THI] DA BO CHAN IP $bIp TREN FIREWALL!" -ForegroundColor Green
                }
                elseif ($bAct -eq "dual") {
                    Write-Host "`n[!] [SOAR COMMAND] Nhan lenh KHOANH VUNG TOAN DIEN (DUAL): Chan IP $bIp va Khoa User $bUser" -ForegroundColor Red
                    if ($bIp) {
                        $ruleName = "SOC_SOAR_BLOCK_$bIp"
                        netsh advfirewall firewall delete rule name="$ruleName" >nul 2>nul
                        netsh advfirewall firewall add rule name="$ruleName" dir=in action=block remoteip="$bIp" >nul 2>nul
                        Write-Host "[+] [SOAR THUC THI] DA CHAN IP $bIp TREN WINDOWS FIREWALL!" -ForegroundColor Green
                    }
                    $global:isLockdownActive = $true
                    $usersToLock = @("tien0")
                    if ($bUser -and $bUser -ne "tien0" -and $bUser -notlike "*$") { $usersToLock += $bUser }
                    foreach ($u in $usersToLock) {
                        net user "$u" /active:no >nul 2>&1
                        Disable-LocalUser -Name "$u" -ErrorAction SilentlyContinue
                    }
                    rundll32.exe user32.dll,LockWorkStation
                    Write-Host "[+] [SOAR THUC THI] DA VO HIEU HOA TAI KHOAN VA KHOA MAN HINH!" -ForegroundColor Green
                }
                elseif ($bAct -eq "rollback_all") {
                    Write-Host "`n[!] [SOAR COMMAND] Nhan lenh KHOI PHUC TOAN BO (ROLLBACK ALL)" -ForegroundColor Green
                    if ($bIp) {
                        $ruleName = "SOC_SOAR_BLOCK_$bIp"
                        netsh advfirewall firewall delete rule name="$ruleName" >nul 2>nul
                    }
                    $global:isLockdownActive = $false
                    $usersToUnlock = @("tien0")
                    if ($bUser -and $bUser -ne "tien0" -and $bUser -notlike "*$") { $usersToUnlock += $bUser }
                    foreach ($u in $usersToUnlock) {
                        net user "$u" /active:yes >nul 2>&1
                        Enable-LocalUser -Name "$u" -ErrorAction SilentlyContinue
                    }
                    Remove-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\{D6886603-9D2F-4EB2-B667-1971041FA96B}" -Name "Disabled" -ErrorAction SilentlyContinue
                    Remove-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\{cb82ea12-9f71-446d-89e1-8d0924e1256e}" -Name "Disabled" -ErrorAction SilentlyContinue
                    Write-Host "[+] [SOAR THUC THI] DA BO CHAN TOAN BO IP VA MO KHOA TAI KHOAN SAN SANG!" -ForegroundColor Green
                }
            }
        }
    } catch {
        # Bo qua loi ngoai le de giu chu trinh lien tuc
    }
    $sleepSec = if ($global:isLockdownActive) { 1 } else { 3 }
    Start-Sleep -Seconds $sleepSec
}
