<#
.SYNOPSIS
    One-command EuroNCAP scenario batch validation.

.DESCRIPTION
    Hand over the root folder that holds the batches (e.g. "...\01_Batch 1"). This finds
    every scenario folder underneath it, no matter how deeply nested, validates each one,
    writes the per-folder reports in place, and produces a single root-level
    Summary_Stats_*.xlsx dashboard so a reviewer can triage the whole batch at a glance.

    Python does the work; this script just locates the interpreter and forwards the run.

.PARAMETER Root
    Root folder to scan. Nested batch/category folders are handled automatically.

.PARAMETER Config
    Optional path to config.json / config.xlsx.

.PARAMETER Summary
    Optional path for the root summary workbook (defaults to one inside Root).

.PARAMETER NoChecklist
    Do not write the per-folder reviewer checklist (Review_Checklist_*.xlsx).

.PARAMETER NoReports
    Skip per-folder reports entirely; write only the root summary.

.PARAMETER Quiet
    Suppress per-scenario progress lines.

.PARAMETER Python
    Override the Python interpreter (e.g. a venv python.exe).

.EXAMPLE
    pwsh -File run_batch.ps1 -Root "D:\Scenarios\01_Batch 1"

.NOTES
    If PowerShell blocks the script, run it as:
        pwsh -ExecutionPolicy Bypass -File run_batch.ps1 -Root "<path>"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Root,
    [string]$Config,
    [string]$Summary,
    [switch]$NoChecklist,
    [switch]$NoReports,
    [switch]$Quiet,
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'tools/batch_validate.py'

if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    Write-Error "Root folder not found: $Root"
    exit 1
}
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    Write-Error "Cannot find batch_validate.py at $script"
    exit 1
}

function Resolve-Python {
    param([string]$Override)
    if ($Override) {
        if (-not (Get-Command $Override -ErrorAction SilentlyContinue)) {
            Write-Error "Python override not found: $Override"
            exit 1
        }
        return [pscustomobject]@{ Exe = $Override; Pre = @() }
    }
    # Prefer the Windows launcher 'py -3'; fall back to python / python3 on PATH.
    if (Get-Command 'py' -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{ Exe = 'py'; Pre = @('-3') }
    }
    foreach ($exe in 'python', 'python3') {
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            return [pscustomobject]@{ Exe = $exe; Pre = @() }
        }
    }
    return $null
}

$py = Resolve-Python -Override $Python
if (-not $py) {
    Write-Error "No Python interpreter found (tried 'py -3', 'python', 'python3'). Pass -Python <path>."
    exit 1
}

$forward = @($script, $Root)
if ($Config)      { $forward += @('--config', $Config) }
if ($Summary)     { $forward += @('--summary', $Summary) }
if ($NoChecklist) { $forward += '--no-checklist' }
if ($NoReports)   { $forward += '--no-reports' }
if ($Quiet)       { $forward += '--quiet' }

$allArgs = @($py.Pre) + $forward

Write-Host "Validating batch under: $Root"
& $py.Exe @allArgs
exit $LASTEXITCODE
