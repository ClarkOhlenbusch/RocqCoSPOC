[CmdletBinding()]
param(
  [Parameter(Mandatory)]
  [string]$FilePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot\..

if (-not (Test-Path $FilePath)) {
  throw "Target file not found: $FilePath"
}

$coqBin = "C:\Users\clark\scoop\apps\coq\2025.01.0\bin\coqc.exe"
if (-not (Test-Path $coqBin)) { $coqBin = "coqc" }

# Parse _CoqProject for -R / -Q flags.
$coqArgs = @()
Get-Content _CoqProject | ForEach-Object {
  $line = $_.Trim()
  if ($line -eq "") { return }
  if ($line -match '^-R\s+(.+)\s+(.+)$') { $coqArgs += "-R", $Matches[1].Trim(), $Matches[2].Trim(); return }
  if ($line -match '^-Q\s+(.+)\s+(.+)$') { $coqArgs += "-Q", $Matches[1].Trim(), $Matches[2].Trim(); return }
}

Write-Host "Checking $FilePath ..."
& $coqBin @coqArgs $FilePath
if ($LASTEXITCODE -ne 0) {
  Write-Error "Proof check failed: $FilePath"
  exit $LASTEXITCODE
}

Write-Host "Proof check passed: $FilePath"
