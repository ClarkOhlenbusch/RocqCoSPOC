[CmdletBinding()]
param(
  [Parameter(Mandatory)]
  [string]$FilePath,

  [Parameter(Mandatory)]
  [int]$CursorLine,

  [string]$StateName = "State 0",

  [string]$CoqTop
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-CoqTopPath {
  param([string]$ExplicitPath)

  if ($ExplicitPath) {
    if (Test-Path $ExplicitPath) {
      return (Resolve-Path $ExplicitPath).Path
    }
    throw "The supplied -CoqTop path was not found: $ExplicitPath"
  }

  $repoRoot = Split-Path -Parent (Resolve-Path $FilePath).Path
  $settingsPath = Join-Path $repoRoot ".vscode\settings.json"
  if (Test-Path $settingsPath) {
    try {
      $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
      $candidate = $null

      if ($settings.psobject.Properties["vscoq.path"]) {
        $candidate = $settings.'vscoq.path'
      }

      if ($candidate -and (Test-Path $candidate)) {
        $coqtopFromVscoq = Join-Path (Split-Path $candidate) "coqtop.exe"
        if (Test-Path $coqtopFromVscoq) { return (Resolve-Path $coqtopFromVscoq).Path }
      }

      if ($settings.psobject.Properties["coqtop.path"]) {
        $candidate = $settings.'coqtop.path'
        if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
      }
    }
    catch {
      Write-Verbose "Could not parse .vscode/settings.json for a coqtop path."
    }
  }

  $fromCheck = Join-Path $repoRoot "scripts\check-proofs.ps1"
  if (Test-Path $fromCheck) {
    $line = Get-Content -LiteralPath $fromCheck | Where-Object { $_ -match '^\s*\$coqBin' } | Select-Object -First 1
    if ($line -and $line -match '["]([^"]+)[\\/]coqc\.exe["]') {
      $coqtop = $Matches[1] + "\coqtop.exe"
      $coqtop = $coqtop.Trim()
      if (Test-Path $coqtop) {
        return (Resolve-Path $coqtop).Path
      }
    }
  }

  $coqTopCmd = Get-Command coqtop -ErrorAction SilentlyContinue
  if ($coqTopCmd) { return $coqTopCmd.Source }
  $coqTopExe = Get-Command coqtop.exe -ErrorAction SilentlyContinue
  if ($coqTopExe) { return $coqTopExe.Source }

  throw "Could not find coqtop. Set -CoqTop to an explicit executable path."
}

function Get-CoqProjectArgs {
  param([string]$ProjectRoot)

  $coqArgs = New-Object System.Collections.Generic.List[string]
  $project = Join-Path $ProjectRoot "_CoqProject"
  if (-not (Test-Path $project)) {
    return $coqArgs.ToArray()
  }

  foreach ($line in Get-Content -LiteralPath $project) {
    $text = $line.Trim()
    if ($text -match '^-R\s+(.+)\s+(\S+)\s*$') {
      $coqArgs.Add("-R")
      $coqArgs.Add($Matches[1].Trim())
      $coqArgs.Add($Matches[2].Trim())
    }
    elseif ($text -match '^-Q\s+(.+)\s+(\S+)\s*$') {
      $coqArgs.Add("-Q")
      $coqArgs.Add($Matches[1].Trim())
      $coqArgs.Add($Matches[2].Trim())
    }
  }

  $coqArgs.ToArray()
}

function Parse-ProofState {
  param([string]$OutputText, [string]$StateLabel)

  if ([string]::IsNullOrWhiteSpace($OutputText)) {
    return $null
  }

  $lines = $OutputText -split "`r?`n"
  $sep = "============================"
  $sepIdx = -1
  for ($i = $lines.Length - 1; $i -ge 0; $i--) {
    if ($lines[$i].Trim() -eq $sep) {
      $sepIdx = $i
      break
    }
  }

  if ($sepIdx -lt 0) {
    return $null
  }

  $hyps = New-Object System.Collections.Generic.List[string]
  for ($i = $sepIdx - 1; $i -ge 0; $i--) {
    $line = $lines[$i].Trim()
    if ($line -eq "") { continue }
    if ($line -match '^\d+\s+goals?$') { break }
    if ($line -match '^No goals\.?$' -or $line -match '^No more goals\.?$') { continue }
    if ($line -match '^Welcome to Coq' -or $line -match '^Coq ' ) { continue }
    if ($line -match '^\S+\s*<\s*$') { continue }
    [void]$hyps.Insert(0, $line)
  }

  $goal = New-Object System.Collections.Generic.List[string]
  for ($i = $sepIdx + 1; $i -lt $lines.Length; $i++) {
    $line = $lines[$i].Trim()
    if ($line -eq "") { continue }
    if ($line -match '^No goals\.?$' -or $line -match '^No more goals\.?$') {
      return @(
        "${StateLabel}:",
        "No Goals"
      ) -join "`n"
    }
    if ($line -match '^\d+\s+goals?$') { continue }
    if ($line -match '^Welcome to Coq' -or $line -match '^Coq ') { continue }
    if ($line -match '^\S+\s*<\s*$') { continue }
    if ($line -match '^-+$') { continue }
    [void]$goal.Add($line)
  }

  if ($goal.Count -eq 0) {
    return @(
      "${StateLabel}:",
      "No Goals"
    ) -join "`n"
  }

  @(
    "${StateLabel}:"
    ($hyps | ForEach-Object { $_ })
    $sep
    ($goal -join "`n")
  ) -join "`n"
}

$resolvedFile = Resolve-Path $FilePath
$repoRoot = Split-Path -Parent $resolvedFile.Path
$allLines = Get-Content -LiteralPath $resolvedFile.Path
$lineCount = $allLines.Length

if ($CursorLine -lt 1 -or $CursorLine -gt $lineCount) {
  throw "CursorLine must be between 1 and $lineCount for file $FilePath"
}

$idx = $CursorLine - 1
$start = 0
for ($i = $idx; $i -ge 0; $i--) {
  if ($allLines[$i] -match '^\s*(Theorem|Lemma|Example|Corollary|Proposition|Remark|Fact|Definition|Goal)\b') {
    $start = $i
    break
  }
}

$prefix = if ($start -gt 0) { $allLines[0..($start - 1)] } else { @() }
$snippet = $allLines[$start..$idx]

$depth = 0
foreach ($line in $snippet) {
  if ($line -match '^\s*Proof\b') { $depth += 1 }
  if ($line -match '^\s*(Qed|Defined|Admitted|Abort)\.?\b') {
    if ($depth -gt 0) { $depth -= 1 }
  }
}

if ($depth -le 0) {
  Write-Output ($StateName + ":")
  Write-Output "No Goals"
  return
}

$coqTop = Resolve-CoqTopPath -ExplicitPath $CoqTop
$coqArgs = @("-q")
$coqArgs += Get-CoqProjectArgs -ProjectRoot $repoRoot

$tempInput = Join-Path $env:TEMP ("coq-state-" + [guid]::NewGuid().ToString("N") + ".v")
$tempOut = Join-Path $env:TEMP ("coq-state-" + [guid]::NewGuid().ToString("N") + ".out")
$tempErr = Join-Path $env:TEMP ("coq-state-" + [guid]::NewGuid().ToString("N") + ".err")

try {
  $scriptBody = New-Object System.Collections.Generic.List[string]
  $scriptBody.Add("(* Auto-generated proof state snapshot for agent pipeline. *)")
  foreach ($line in @($prefix)) { [void]$scriptBody.Add([string]$line) }
  foreach ($line in @($snippet)) { [void]$scriptBody.Add([string]$line) }
  $scriptBody.Add("Show.")
  $scriptBody.Add("Abort.")
  $scriptText = $scriptBody -join [Environment]::NewLine

  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($tempInput, $scriptText, $utf8NoBom)

  $proc = Start-Process -FilePath $coqTop -ArgumentList $coqArgs -NoNewWindow -PassThru -Wait `
    -RedirectStandardInput $tempInput -RedirectStandardOutput $tempOut -RedirectStandardError $tempErr

  $rawOut = if (Test-Path $tempOut) { Get-Content -LiteralPath $tempOut -Raw } else { "" }
  $rawErr = if (Test-Path $tempErr) { Get-Content -LiteralPath $tempErr -Raw } else { "" }

  if (-not [string]::IsNullOrWhiteSpace($rawErr) -and ($rawErr -match 'Error:')) {
    Write-Error $rawErr
    return
  }

  if ($proc.ExitCode -ne 0 -and [string]::IsNullOrWhiteSpace($rawOut)) {
    if (-not [string]::IsNullOrWhiteSpace($rawErr)) {
      Write-Error $rawErr
      return
    }
    Write-Error "coqtop failed with code $($proc.ExitCode)."
    return
  }

  $stateText = Parse-ProofState -OutputText ($rawOut + "`n" + $rawErr) -StateLabel $StateName
  if ($stateText) {
    Write-Output $stateText
  }
  else {
    Write-Error "Could not parse coqtop output into a proof state."
    Write-Verbose ($rawOut + "`n" + $rawErr)
    return
  }
}
finally {
  if (Test-Path $tempInput) { Remove-Item $tempInput -Force }
  if (Test-Path $tempOut) { Remove-Item $tempOut -Force }
  if (Test-Path $tempErr) { Remove-Item $tempErr -Force }
}
