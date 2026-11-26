# Chay cac buoc demo tren CVAT local. Hoi tai khoan CVAT (mat khau an), chi giu trong tien trinh nay.
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo.ps1 -Step setup -Recreate
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo.ps1 -Step calib,qc
# Cac buoc: setup (tao project/task/job demo), calib (task hieu chinh quy uoc cuboid), dryrun, qc, apply
# Duong dan mac dinh (data\demo_data, configs\profile.json, data\logs) lay tu cuboidqc\paths.py.
param(
    [string]$Step = 'qc',      # mot hoac nhieu buoc cach nhau bang dau phay, vd. calib,qc
    [switch]$Recreate
)
$ErrorActionPreference = 'Stop'
$valid = @('setup', 'calib', 'qc', 'dryrun', 'apply')
$steps = @($Step -split '[,\s]+' | Where-Object { $_ })
foreach ($s in $steps) {
    if ($valid -notcontains $s) { throw "Buoc khong hop le: '$s'. Hop le: $($valid -join ', ')" }
}
Set-Location (Split-Path -Parent $PSScriptRoot)      # thu muc goc cua repo
$logs = 'data\logs'
New-Item -ItemType Directory -Force $logs | Out-Null

if (-not $env:CVAT_TOKEN -and -not $env:CVAT_PASS -and (Test-Path .\.cvat_login.xml)) {
    # dang nhap da luu bang save_login.ps1 (ma hoa DPAPI, chi giai ma duoc boi chinh ban tren may nay)
    $saved = Import-Clixml .\.cvat_login.xml
    $env:CVAT_USER = $saved.UserName
    $env:CVAT_PASS = $saved.GetNetworkCredential().Password
}
if (-not $env:CVAT_TOKEN) {
    if (-not $env:CVAT_USER) { $env:CVAT_USER = Read-Host 'CVAT username' }
    if (-not $env:CVAT_PASS) {
        $sec = Read-Host 'CVAT password (an ky tu)' -AsSecureString
        $env:CVAT_PASS = [System.Net.NetworkCredential]::new('', $sec).Password
    }
}
try {
    $i = 0
    foreach ($s in $steps) {
        $i++
        $log = "$logs\demo_{0}_{1}.log" -f $i, $s     # moi buoc mot log rieng (khong ghi de khi lap lai buoc qc)
        Write-Host "=== $s ==="
        switch ($s) {
            'setup'  { $a = @('-m', 'cuboidqc.cvat.setup'); if ($Recreate) { $a += '--recreate' }; python @a 2>&1 | Tee-Object -FilePath $log }
            'calib'  { python -m cuboidqc.cvat.calibrate 2>&1 | Tee-Object -FilePath $log }
            'dryrun' { python -m cuboidqc.cvat.runner --dry-run 2>&1 | Tee-Object -FilePath $log }
            'qc'     { python -m cuboidqc.cvat.runner 2>&1 | Tee-Object -FilePath $log }
            'apply'  { python -m cuboidqc.cvat.runner --apply 2>&1 | Tee-Object -FilePath $log }
        }
    }
}
finally {
    Remove-Item Env:CVAT_PASS -ErrorAction SilentlyContinue
    Remove-Item Env:CVAT_USER -ErrorAction SilentlyContinue
}
