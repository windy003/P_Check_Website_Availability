$ErrorActionPreference = 'Stop'

$procs = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*D:\files\using\Python\P_Check_Website_Availability\monitor.py*' }

if (-not $procs) {
    Write-Host "No matching process found (jdbendi.com\flask\app.py)." -ForegroundColor Yellow
} else {
    foreach ($p in $procs) {
        Write-Host "Killing PID $($p.ProcessId): $($p.CommandLine)" -ForegroundColor Cyan
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Host "  Killed PID $($p.ProcessId)" -ForegroundColor Green
        } catch {
            Write-Host "  Failed to kill PID $($p.ProcessId): $_" -ForegroundColor Red
        }
    }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Start-Sleep -Seconds 3
