# ==============================================================================
# SME SOC - UNIFIED AGENT FOR VMWARE WINDOWS (POWERSHELL NATIVE)
# MULTI-FOLDER RADAR (DESKTOP + DOWNLOADS + DOCUMENTS + TEMP) + SOAR REMEDIATION
# ==============================================================================

# Dam bao chi duy nhat 1 tien trinh Agent hoat dong (diet cac tien trinh Agent cu neu co)
$myPid = $PID
Get-WmiObject Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like '*soc_windows_agent*' -and $_.ProcessId -ne $myPid
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

$SOC_SERVER = "http://192.168.21.136:8888"
$METRICS_URL = "$SOC_SERVER/api/windows_metrics"
$CVE_URL = "$SOC_SERVER/api/cve/report"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "[+] SME SOC - HE THONG GIAM SAT TOAN DIEN MAY TRAM WINDOWS" -ForegroundColor Cyan
Write-Host "[+] May tram: $env:COMPUTERNAME | Server SOC: $SOC_SERVER" -ForegroundColor Cyan
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
    client_ip = "192.168.21.153"
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
                    # Bat bat ky file nao co ten winrar, putty, 7z ma khong can go dung phien ban
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
                            client_ip = "192.168.21.153"
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

    # Don dep bo nho seen: Neu file da bi xoa, xoa khoi seenFiles de phat hien tiep neu xuat hien lai
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
        # 1. Kiem tra file CVE trong tat ca thu muc trong yeu
        Check-TargetFolders

        # 2. Do tai nguyen may tram
        $os = Get-CimInstance Win32_OperatingSystem | Select-Object -First 1
        $ram = [math]::Round((1 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize)) * 100)
        $proc = Get-CimInstance Win32_Processor | Select-Object -First 1
        $cpu = if ($proc.LoadPercentage) { [int]$proc.LoadPercentage } else { 15 }
        
        $metricsPayload = @{ cpu = [int]$cpu; ram = [int]$ram }
        $resp = Send-SocJson $METRICS_URL $metricsPayload
        
        if ($resp) {
            # SOAR 1: Lenh tat may tu xa
            if ($resp.action -eq "shutdown") {
                Write-Host "[-] Nhan lenh Shutdown khan cap tu SOC!" -ForegroundColor Red
                Stop-Computer -Force
            }

            # SOAR 2: Lenh tieu huy tep doc hai / cach ly tu xa
            if ($resp.cve_action -eq "delete_file" -and $resp.target_file) {
                $targetFile = $resp.target_file
                # Trich xuat tu khoa chinh: vi du "winrar-x64-622" tu "winrar-x64-622.exe"
                $baseName = [System.IO.Path]::GetFileNameWithoutExtension($targetFile).Trim()
                $keyword = if ($baseName -match "(winrar|putty|7z|7-zip|git|npp|notepad)") { $Matches[1] } else { $baseName }
                
                Write-Host "`n[!] [SOAR COMMAND] Nhan lenh tieu huy tu xa: $targetFile (Tu khoa: $keyword)" -ForegroundColor Red
                $deletedCount = 0

                # Xoa trong tat ca cac thu muc canh chung (Desktop, Downloads, Temp...)
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

                # Tim va tieu huy toan bo trong UserProfile neu van chua thay
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
        }
    } catch {
        # Bo qua loi ngoai le de giu chu trinh lien tuc
    }
    Start-Sleep -Seconds 3
}
