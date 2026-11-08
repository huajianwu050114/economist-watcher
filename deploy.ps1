param(
    [string] $RepoName = "economist-watcher"
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Require-Cmd([string] $name, [string] $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name is not installed. $hint"
    }
}
Require-Cmd git "Install: winget install --id Git.Git --exact"
Require-Cmd gh "Install: winget install --id GitHub.cli --exact (then restart PowerShell)"

Write-Host "Checking GitHub authentication..." -ForegroundColor Cyan
& gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Please sign into GitHub using the browser..." -ForegroundColor Yellow
    & gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) { throw "GitHub authorization failed." }
}

if (-not (Test-Path .git)) {
    & git init -b main
    if ($LASTEXITCODE -ne 0) { throw "git init failed" }
}
& git add -A
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    & git -c user.name="Economist Watcher Setup" -c user.email="setup@users.noreply.github.com" commit -m "Initial Economist Watcher"
    if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
}

& git remote get-url origin 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "This folder already has a GitHub remote. Skipping creation." -ForegroundColor Yellow
    & git remote -v
} else {
    Write-Host "Creating a PRIVATE GitHub repository and uploading the project..." -ForegroundColor Cyan
    & gh repo create $RepoName --private --source . --remote origin --push
    if ($LASTEXITCODE -ne 0) { throw "Could not create/upload repository. See the message above." }
}

$fullName = (& gh repo view --json nameWithOwner --jq '.nameWithOwner').Trim()
if ($LASTEXITCODE -ne 0 -or -not $fullName) { throw "Repository could not be resolved" }
Write-Host "" 
Write-Host "Success. Repository: https://github.com/$fullName" -ForegroundColor Green
Write-Host "Next: open https://github.com/$fullName/actions" -ForegroundColor Green
Write-Host "Select Economist Watcher -> Run workflow to test immediately." -ForegroundColor Green
Write-Host "If GitHub Actions asks to enable workflows, enable it for this repository." -ForegroundColor Yellow
