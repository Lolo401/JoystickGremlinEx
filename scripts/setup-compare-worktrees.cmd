@echo off
REM Create sibling worktrees on Windows for Muchimi vs Laurent compare.
REM Run from ANY checkout of Lolo401/JoystickGremlinEx that already has remotes set.
REM
REM Result:
REM   C:\GEX\muchimi-experimental  -> branch compare/muchimi-experimental (Muchimi stock)
REM   C:\GEX\lolo                  -> branch compare/lolo (Laurent sandbox, m77T62L)

setlocal EnableExtensions
set "GEX_ROOT=C:\GEX"
set "REPO=%~dp0.."
pushd "%REPO%" || exit /b 1

git remote get-url upstream >nul 2>&1 || git remote add upstream https://github.com/muchimi/JoystickGremlinEx.git
git fetch upstream experimental
git fetch origin compare/muchimi-experimental compare/lolo 2>nul

if not exist "%GEX_ROOT%" mkdir "%GEX_ROOT%"

git worktree list | findstr /I /C:"muchimi-experimental" >nul
if errorlevel 1 (
  git branch --track compare/muchimi-experimental upstream/experimental 2>nul
  git worktree add "%GEX_ROOT%\muchimi-experimental" compare/muchimi-experimental
) else (
  echo muchimi-experimental worktree already registered
)

git worktree list | findstr /I /C:"\\lolo" >nul
if errorlevel 1 (
  git worktree add "%GEX_ROOT%\lolo" compare/lolo
) else (
  echo lolo worktree already registered
)

echo.
echo Worktrees:
git worktree list
echo.
echo Next: powershell -ExecutionPolicy Bypass -File "%GEX_ROOT%\lolo\scripts\create-desktop-shortcuts.ps1"
popd
