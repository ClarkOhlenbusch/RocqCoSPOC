# Check all Coq/Rocq proofs in this project.
# Run from repo root: .\scripts\check-proofs.ps1
# Used by the IDE agent to verify proofs after applying tactics.

Set-Location $PSScriptRoot\..

$coqBin = "C:\Users\clark\scoop\apps\coq\2025.01.0\bin\coqc.exe"
if (-not (Test-Path $coqBin)) { $coqBin = "coqc" }

# Parse _CoqProject for -R / -Q and .v files
$coqArgs = @()
$vFiles = @()
Get-Content _CoqProject | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "") { return }
    if ($line -match '^-R\s+(.+)\s+(.+)$') { $coqArgs += "-R", $Matches[1].Trim(), $Matches[2].Trim(); return }
    if ($line -match '^-Q\s+(.+)\s+(.+)$') { $coqArgs += "-Q", $Matches[1].Trim(), $Matches[2].Trim(); return }
    if ($line -match '\.v\s*$') { $vFiles += $line }
}

foreach ($v in $vFiles) {
    if (-not (Test-Path $v)) { continue }
    Write-Host "Checking $v ..."
    & $coqBin @coqArgs $v
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Proof check failed: $v"
        exit $LASTEXITCODE
    }
}
Write-Host "All proofs checked."
