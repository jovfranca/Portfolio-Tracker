param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$pythonExe = Join-Path (Get-Location) '.venv/Scripts/python.exe'
if (!(Test-Path $pythonExe)) { throw 'Crie o ambiente Python seguindo docs/setup.md.' }
if (!(Test-Path '.env')) { throw 'Configure .env seguindo docs/setup.md.' }

# The optional portable cluster belongs only to this workspace.
if (Test-Path '.local/pgsql/bin/pg_ctl.exe') {
    & .local/pgsql/bin/pg_isready.exe -h 127.0.0.1 -p 5432 *> $null
    if ($LASTEXITCODE -ne 0) {
        & .local/pgsql/bin/pg_ctl.exe -D .local/pgdata -l .local/postgres.log -o '-h 127.0.0.1 -p 5432' -w start
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao iniciar PostgreSQL.' }
    }
}
& $pythonExe -m src.bootstrap
if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar banco. Verifique DATABASE_URL e PostgreSQL.' }
& $pythonExe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Falha na migracao do banco.' }
& $pythonExe -m src.instrument_catalog
if ($LASTEXITCODE -ne 0) { throw 'Falha ao carregar o catalogo de instrumentos.' }
if (!$SkipBuild) {
    Push-Location frontend
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar frontend.' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar frontend.' }
    } finally { Pop-Location }
}
if (!(Test-Path 'frontend/dist/index.html')) { throw 'Compile o frontend antes de usar -SkipBuild.' }
Write-Host 'Abra http://127.0.0.1:8000. Ctrl+C encerra a aplicacao; o banco continua ativo.'
& $pythonExe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
