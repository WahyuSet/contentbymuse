# Menjalankan API, worker, dan web (Windows, sesuai Spec §1.3).
# Prasyarat: uv, pnpm, file backend/.env terisi (lihat backend/.env.example).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; uv run uvicorn app.main:serve --factory --host 127.0.0.1 --port 8010"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; uv run python -m app.worker"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; pnpm dev"
Write-Host "API http://127.0.0.1:8010  ·  Web http://localhost:5180"
