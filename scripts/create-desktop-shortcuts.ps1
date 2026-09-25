# Create desktop shortcuts for side-by-side GremlinEx compare launches.
# Run once on the Windows machine after worktrees exist at the paths below
# (or pass -MuchimiRoot / -LoloRoot).
#
# Example:
#   powershell -ExecutionPolicy Bypass -File .\scripts\create-desktop-shortcuts.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\create-desktop-shortcuts.ps1 `
#     -MuchimiRoot 'C:\GEX\muchimi-experimental' -LoloRoot 'C:\GEX\lolo'

param(
    [string]$MuchimiRoot = 'C:\GEX\muchimi-experimental',
    [string]$LoloRoot = 'C:\GEX\lolo',
    [string]$Desktop = [Environment]::GetFolderPath('Desktop')
)

$ErrorActionPreference = 'Stop'
$wsh = New-Object -ComObject WScript.Shell

function New-GexShortcut {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Description
    )
    $launcher = Join-Path $Root 'launch-gex.cmd'
    if (-not (Test-Path $launcher)) {
        Write-Warning "Launcher missing: $launcher — create the worktree first, then re-run."
        return
    }
    $lnkPath = Join-Path $Desktop "$Name.lnk"
    $sc = $wsh.CreateShortcut($lnkPath)
    $sc.TargetPath = $launcher
    $sc.WorkingDirectory = $Root
    $sc.WindowStyle = 1
    $sc.Description = $Description
    $icon = Join-Path $Root 'gremlinex.png'
    if (Test-Path $icon) { $sc.IconLocation = $icon }
    $sc.Save()
    Write-Host "Created: $lnkPath -> $launcher"
}

New-GexShortcut `
    -Name 'GremlinEx Muchimi (experimental)' `
    -Root $MuchimiRoot `
    -Description 'Stock Muchimi experimental — compare baseline'

New-GexShortcut `
    -Name 'GremlinEx Lolo (compare)' `
    -Root $LoloRoot `
    -Description 'Laurent compare sandbox (APPLICATION_BASE m77T62L)'

Write-Host ''
Write-Host 'Window titles should show different APPLICATION_BASE tags.'
Write-Host 'With per-version data folders enabled, configs live under separate Joystick Gremlin Ex_* folders.'
