# Install the T62 / T62L desktop pair — same pattern as T57 / T57L.
#
# Run on your Windows machine from ANY JoystickGremlinEx checkout that has
# .venv and can fetch origin:
#
#   git fetch origin T62 T62L
#   git checkout T62L
#   .\scripts\install_t62_desktop_pair.ps1
#
# Creates (or refreshes):
#   Desktop\GremlinEx T62.lnk   → sibling worktree JoystickGremlinEx-T62  (Muchimi)
#   Desktop\GremlinEx T62L.lnk  → sibling worktree JoystickGremlinEx-T62L (Laurent)

[CmdletBinding()]
param(
    [string]$DesktopPath = ([Environment]::GetFolderPath('Desktop'))
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Maker = Join-Path $PSScriptRoot 'create_branch_shortcut.ps1'

if (-not (Test-Path $Maker)) {
    throw "Missing $Maker — run this from a checkout that includes scripts/create_branch_shortcut.ps1"
}

Push-Location $RepoRoot
try {
    git fetch origin T62 T62L
    if ($LASTEXITCODE -ne 0) { throw 'git fetch origin T62 T62L failed' }

    # Ensure local branches point at origin tips
    git branch -f T62 origin/T62 2>$null
    git branch -f T62L origin/T62L 2>$null

    Write-Host '=== GremlinEx T62 (Muchimi experimental) ==='
    & $Maker -Branch T62 -CreateWorktree -DesktopPath $DesktopPath -ShortcutName 'GremlinEx T62'

    Write-Host ''
    Write-Host '=== GremlinEx T62L (Laurent) ==='
    & $Maker -Branch T62L -CreateWorktree -DesktopPath $DesktopPath -ShortcutName 'GremlinEx T62L'
}
finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Done. You should see "GremlinEx T62" and "GremlinEx T62L" next to your T57 / T57L icons.'
Write-Host 'Window titles: m77T62 vs m77T62L.'
