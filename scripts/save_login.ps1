# Chay MOT LAN de khong phai go lai mat khau CVAT moi lan chay demo.ps1.
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\save_login.ps1
# Thong tin duoc ma hoa bang Windows DPAPI (Export-Clixml): chi tai khoan Windows nay tren may nay giai ma duoc.
# Xoa file .cvat_login.xml (o thu muc goc) la het. Khong dua file nay vao git / khong gui cho ai.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)      # thu muc goc cua repo
$u = Read-Host 'CVAT username'
$p = Read-Host 'CVAT password (an ky tu)' -AsSecureString
[pscredential]::new($u, $p) | Export-Clixml -Path .\.cvat_login.xml
Write-Host 'Da luu .cvat_login.xml (ma hoa DPAPI).'
