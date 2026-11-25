param(
    [ValidateSet('setup', 'check', 'test', 'serve')]
    [string]$Action = 'check',
    [int]$Port = 8000,
    [switch]$Live,
    [string]$PythonPath = ''
)
$ErrorActionPreference = 'Stop'
$condaRoot = Join-Path $env:USERPROFILE 'Softwares\miniconda'
if (-not $PythonPath) {
    $PythonPath = Join-Path $condaRoot 'envs\test\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    if ($Action -ne 'setup') { throw 'Run .\dev.ps1 setup first, or provide -PythonPath.' }
    $condaExe = Join-Path $condaRoot 'Scripts\conda.exe'
    if (-not (Test-Path -LiteralPath $condaExe)) { throw 'Miniconda not found.' }
    & $condaExe create --name test python=3.11 --yes
    if ($LASTEXITCODE -ne 0) { throw 'Conda environment creation failed.' }
    if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Requested Python executable not found.' }
}
$launcherArgs = @((Join-Path $PSScriptRoot 'scripts\local_dev.py'), $Action, '--port', $Port)
if ($Live) { $launcherArgs += '--live' }
& $PythonPath @launcherArgs
exit $LASTEXITCODE
