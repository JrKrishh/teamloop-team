# Install Super Agents for the current user: copies this folder to %LOCALAPPDATA%\TeamLoop (the hooks of connected
# repos point there), adds it to your PATH for the `teamloop` command, makes Start-menu and desktop shortcuts, and
# opens the app. Run "Install Super Agents.cmd", or:  powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$dst = Join-Path $env:LOCALAPPDATA "TeamLoop"
New-Item -ItemType Directory -Force -Path $dst | Out-Null

# an older copy that is running locks its files: close the app, and ask about a running hub
Get-Process -Name SuperAgents -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $dst "SuperAgents.exe") } | Stop-Process -Force
Start-Sleep -Milliseconds 500
try {
    Copy-Item -Path (Join-Path $src "*") -Destination $dst -Recurse -Force
} catch {
    Write-Host "Couldn't replace the files in $dst. If 'teamloop hub' is running, stop it (Ctrl+C in its window) and run the installer again." -ForegroundColor Yellow
    throw
}

$path = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not ($path -split ";" | Where-Object { $_ -eq $dst })) {
    [Environment]::SetEnvironmentVariable("Path", ($path.TrimEnd(";") + ";" + $dst), "User")
}

$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop"))) {
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $dir "TeamLoop.lnk")  # the name before 0.3
    $lnk = $shell.CreateShortcut((Join-Path $dir "Super Agents.lnk"))
    $lnk.TargetPath = Join-Path $dst "SuperAgents.exe"
    $lnk.IconLocation = (Join-Path $dst "SuperAgents.exe") + ",0"
    $lnk.WorkingDirectory = $env:USERPROFILE
    $lnk.Description = "Super Agents: your team's AI agents, on one page"
    $lnk.Save()
}
Write-Host "Installed Super Agents in $dst. Opening it now."
Start-Process (Join-Path $dst "SuperAgents.exe")
