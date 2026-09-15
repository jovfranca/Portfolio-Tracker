$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
# A dedicated database keeps browser-test records away from the user's portfolio.
$databaseLine = Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
$env:DATABASE_URL = ($databaseLine.Substring(13) -replace '/[^/]+$', '/portfolio_tracker_e2e')
$env:ALLOWED_ORIGINS = 'http://127.0.0.1:8001'
& .venv/Scripts/python.exe -m src.bootstrap
if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar banco de testes.' }
& .venv/Scripts/python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Falha ao migrar banco de testes.' }
& .venv/Scripts/python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8001
