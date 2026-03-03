[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Path = (Join-Path $PSScriptRoot ".."),
    [string[]]$Patterns = @(
        "*.vo",
        "*.vos",
        "*.vok",
        "*.vio",
        "*.glob",
        "*.aux"
    ),
    [switch]$NoRecurse
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Resolve-Path -Path $Path
if (-not (Test-Path $root.Path)) {
    throw "Path does not exist: $Path"
}

$artifacts = New-Object System.Collections.Generic.List[System.IO.FileInfo]
foreach ($pattern in $Patterns) {
    if ($NoRecurse) {
        $candidates = Get-ChildItem -Path $root.Path -Filter $pattern -File -Force -ErrorAction SilentlyContinue
    }
    else {
        $candidates = Get-ChildItem -Path $root.Path -Filter $pattern -Recurse -File -Force -ErrorAction SilentlyContinue
    }

    if ($null -ne $candidates) {
        foreach ($candidate in $candidates) {
            $artifacts.Add($candidate)
        }
    }
}

$uniqueArtifacts = $artifacts | Sort-Object -Property FullName -Unique
if ($uniqueArtifacts.Count -eq 0) {
    Write-Host "No matching Coq artifacts found."
    return
}

$deleted = 0
foreach ($artifact in $uniqueArtifacts) {
    if ($PSCmdlet.ShouldProcess($artifact.FullName, "Delete")) {
        Remove-Item -LiteralPath $artifact.FullName -Force
        $deleted++
    }
}

Write-Host "Cleaned up $deleted generated file(s) in: $($root.Path)"
if (-not $NoRecurse) {
    Write-Host "Used recursive search."
} else {
    Write-Host "Used non-recursive search."
}
