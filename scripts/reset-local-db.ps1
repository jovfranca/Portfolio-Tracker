param([switch]$ConfirmReset)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$pythonExe = Join-Path (Get-Location) '.venv/Scripts/python.exe'
if (!(Test-Path $pythonExe)) { throw 'Crie o ambiente Python seguindo docs/setup.md.' }
if (!(Test-Path '.env')) { throw 'Configure .env seguindo docs/setup.md.' }
if (!$ConfirmReset) {
    throw 'Operacao destrutiva local. Execute novamente com -ConfirmReset.'
}
& $pythonExe -m src.reset_local_db --confirm-local-reset
if ($LASTEXITCODE -ne 0) { throw 'Falha ao reinicializar o banco local.' }
