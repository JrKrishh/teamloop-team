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
# Start menu and desktop shortcuts: running teamloop with no command opens the board
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop"))) {
    $lnk = $shell.CreateShortcut((Join-Path $dir "TeamLoop.lnk"))
    $lnk.TargetPath = Join-Path $dst "teamloop.exe"
    $lnk.WorkingDirectory = $env:USERPROFILE
    $lnk.Description = "TeamLoop: open your team's board"
    $lnk.Save()
}
Write-Host "Installed: $dst\teamloop.exe"
Write-Host "Shortcuts: 'TeamLoop' in the Start menu and on the desktop open your board."
Write-Host "Next (teammate):  teamloop login <invite>   then, in your repo:  teamloop init"
Write-Host "Next (lead):      teamloop hub"
