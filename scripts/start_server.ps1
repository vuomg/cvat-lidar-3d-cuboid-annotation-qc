# Chay server QC cho extension (dung duoc tu bat ky thu muc nao).
#   .\scripts\start_server.ps1                                      # dung configs\profile.json
#   .\scripts\start_server.ps1 --meta data\demo_data\meta.json      # them ego pose de kiem tra huong nguoc
# Moi tham so them vao se chuyen thang cho cuboidqc.server.app (xem: python scripts\run_server.py --help).
Set-Location (Split-Path -Parent $PSScriptRoot)
python -m cuboidqc.server.app @args
