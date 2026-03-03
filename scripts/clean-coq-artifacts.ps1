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
    [switch]$NoRecurse,
    [switch]$ResetVFiles
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

$sourceFiles = New-Object System.Collections.Generic.List[System.IO.FileInfo]
if ($ResetVFiles) {
    if ($NoRecurse) {
        $sources = Get-ChildItem -Path $root.Path -Filter "*.v" -File -Force -ErrorAction SilentlyContinue
    }
    else {
        $sources = Get-ChildItem -Path $root.Path -Filter "*.v" -Recurse -File -Force -ErrorAction SilentlyContinue
    }

    if ($null -ne $sources) {
        foreach ($source in $sources) {
            $sourceFiles.Add($source)
        }
    }
}

$uniqueArtifacts = @($artifacts | Sort-Object -Property FullName -Unique)
if ($uniqueArtifacts.Count -eq 0) {
    Write-Host "No matching Coq artifacts found."
    if (-not $ResetVFiles) { return }
}

$deleted = 0
foreach ($artifact in $uniqueArtifacts) {
    if ($PSCmdlet.ShouldProcess($artifact.FullName, "Delete")) {
        Remove-Item -LiteralPath $artifact.FullName -Force
        $deleted++
    }
}

if ($ResetVFiles) {
    $reset = 0
    foreach ($source in $sourceFiles) {
        if ($PSCmdlet.ShouldProcess($source.FullName, "Empty")) {
            Set-Content -LiteralPath $source.FullName -Value "" -NoNewline
            $reset++
        }
    }
    Write-Host "Emptied $reset source file(s) in: $($root.Path)"
    if ($deleted -eq 0) {
        Write-Host "No matching generated artifacts were found."
    }
} else {
    Write-Host "Cleaned up $deleted generated file(s) in: $($root.Path)"
}
if (-not $NoRecurse) {
    Write-Host "Used recursive search."
} else {
    Write-Host "Used non-recursive search."
}
