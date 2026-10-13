# Install teamloop.exe for the current user: copies the unzipped folder to %LOCALAPPDATA%\TeamLoop and adds it to
# your user PATH. Run from the unzipped folder:  powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$dst = Join-Path $env:LOCALAPPDATA "TeamLoop"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Path (Join-Path $src "*") -Destination $dst -Recurse -Force
$path = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not ($path -split ";" | Where-Object { $_ -eq $dst })) {
    [Environment]::SetEnvironmentVariable("Path", ($path.TrimEnd(";") + ";" + $dst), "User")
    Write-Host "Added $dst to your PATH. Open a new terminal to use 'teamloop'."
}
Write-Host "Installed: $dst\teamloop.exe"
Write-Host "Next (teammate):  teamloop login <invite>   then, in your repo:  teamloop init"
Write-Host "Next (lead):      teamloop hub"
