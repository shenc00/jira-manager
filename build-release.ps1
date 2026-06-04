<#
.SYNOPSIS
  Build a clean, shareable jira-manager.zip and (optionally) publish it.

.DESCRIPTION
  Packages ONLY the committed code via `git archive`, so .env, data/, .git,
  .venv and __pycache__ are never included - your Jira token cannot leak into
  the zip. The zip is written to dist\jira-manager.zip.

  If -Destination is given (e.g. a locally-synced SharePoint folder), the zip is
  copied there, which replaces the shared file once OneDrive syncs it.

.EXAMPLE
  .\build-release.ps1
  .\build-release.ps1 -Destination "C:\Users\you\BD\GSC\Github\jira-manager.zip"
#>
param([string]$Destination = "")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSCommandPath
Push-Location $root
try {
    if (-not (Test-Path "dist")) { New-Item -ItemType Directory "dist" | Out-Null }
    $zip = Join-Path $root "dist\jira-manager.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }

    git archive --format=zip --prefix=jira-manager/ -o $zip HEAD
    if ($LASTEXITCODE -ne 0) {
        throw "git archive failed. Commit your changes first (git status), then retry."
    }

    # Safety check: the zip must NOT contain a real .env (only .env.example).
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
    try {
        $names = @($archive.Entries.FullName)
        if ($names -match '(^|/)\.env$') {
            throw "ABORT: a real .env file is inside the zip. Not publishing."
        }
    } finally { $archive.Dispose() }

    Write-Output ("Built {0} ({1} files)" -f $zip, $names.Count)

    if ($Destination) {
        Copy-Item $zip $Destination -Force
        Write-Output ("Published to {0}" -f $Destination)
        Write-Output "OneDrive will sync it to SharePoint shortly."
    }
    else {
        Write-Output "No -Destination given."
        Write-Output "Upload dist\jira-manager.zip to SharePoint manually, or pass"
        Write-Output "-Destination with a synced SharePoint path to publish automatically."
    }
}
finally {
    Pop-Location
}
