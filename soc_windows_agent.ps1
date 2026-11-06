# ==============================================================================
# SME SOC - UNIFIED AGENT FOR VMWARE WINDOWS (POWERSHELL NATIVE)
# MULTI-FOLDER RADAR (DESKTOP + DOWNLOADS + DOCUMENTS + TEMP) + SOAR REMEDIATION
# ==============================================================================

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
    [System.IO.Path]::Combine($env:USERPROFILE, "Downloads"),
    [System.IO.Path]::Combine($env:USERPROFILE, "Desktop"),
    [System.IO.Path]::Combine($env:USERPROFILE, "Documents"),
    $env:TEMP,
    "C:\Users\Public\Downloads",
    "C:\Users\Public\Desktop"
)

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
    # 1. Quet cac file hien co trong cac thu muc canh chung
    $currentPaths = @{}
    foreach ($folder in $watchFolders) {
        if (Test-Path $folder) {
            Get-ChildItem -Path $folder -File -ErrorAction SilentlyContinue | ForEach-Object {
                $fullPath = $_.FullName
                $currentPaths[$fullPath] = $true
                $fn = $_.Name
                $ext = $_.Extension.ToLower()

                # Neu file chua duoc bao cao
                if (-not $seenFiles.ContainsKey($fullPath)) {
                    if ($ext -in @(".exe", ".msi", ".zip", ".rar", ".7z")) {
                        $cveApp = $null
                        if ($fn -match "winrar.*?(6[._\-]?[0-2][0-2]|6\.22|6\.20|5\.)") {
                            $cveApp = @{ name = "WinRAR (Tep tai ve: $fn)"; version = "6.22.0"; publisher = "win.rar GmbH" }
                        } elseif ($fn -match "putty.*?(0\.[0-7][0-9]|0\.80)") {
                            $cveApp = @{ name = "PuTTY (Tep tai ve: $fn)"; version = "0.80"; publisher = "Simon Tatham" }
                        } elseif ($fn -match "7z.*?(1[0-9]|2[0-2])") {
                            $cveApp = @{ name = "7-Zip (Tep tai ve: $fn)"; version = "22.01"; publisher = "Igor Pavlov" }
                        } elseif ($fn -match "git.*?(2\.[0-3][0-9]|2\.4[0-5])") {
                            $cveApp = @{ name = "Git (Tep tai ve: $fn)"; version = "2.44.0"; publisher = "The Git Development Community" }
                        } elseif ($fn -match "npp|notepad.*?(8\.[0-5])") {
                            $cveApp = @{ name = "Notepad++ (Tep tai ve: $fn)"; version = "8.5.6"; publisher = "Notepad++ Team" }
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
                            $sendRes = Send-SocJson $CVE_URL $payload
                            if ($sendRes) {
                                Write-Host "    -> Da gui canh bao len SOC Dashboard va Telegram thanh cong!" -ForegroundColor Yellow
                            }
                        }
                    }
                }
            }
        }
    }

    # 2. Don dep bo nho seen: Neu file da bi xoa (do SOAR hoac user), xoa khoi seenFiles de phat hien tiep neu xuat hien lai
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
                Write-Host "`n[!] [SOAR COMMAND] Nhan lenh tieu huy tep doc hai tu xa: $targetFile" -ForegroundColor Red
                $deletedCount = 0

                # Xoa trong cac thu muc canh chung
                foreach ($folder in $watchFolders) {
                    if (Test-Path $folder) {
                        $targetPath = [System.IO.Path]::Combine($folder, $targetFile)
                        if (Test-Path $targetPath) {
                            Remove-Item $targetPath -Force -ErrorAction SilentlyContinue
                            Write-Host "[+] [SOAR THUC THI] DA TIEU HUY TEP: $targetPath" -ForegroundColor Green
                            if ($seenFiles.ContainsKey($targetPath)) { $seenFiles.Remove($targetPath) }
                            $deletedCount++
                        }
                    }
                }

                # Xoa ca trong D:\sharemay1 hoac C:\SOC_Agent neu co
                foreach ($extra in @("C:\SOC_Agent", "D:\sharemay1", "Z:\sharemay1")) {
                    if (Test-Path $extra) {
                        $p = [System.IO.Path]::Combine($extra, $targetFile)
                        if (Test-Path $p) {
                            Remove-Item $p -Force -ErrorAction SilentlyContinue
                            Write-Host "[+] [SOAR THUC THI] DA TIEU HUY TEP TAI: $p" -ForegroundColor Green
                            $deletedCount++
                        }
                    }
                }

                # Neu van con sot, tim sau trong toan bo UserProfile de tieu huy
                if ($deletedCount -eq 0) {
                    Get-ChildItem -Path $env:USERPROFILE -Filter $targetFile -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
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
