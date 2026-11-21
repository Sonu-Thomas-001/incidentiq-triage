# Start backend (8000) and frontend (5173) in two windows. Run from the repo root.
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; & '$py' -m uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"
Write-Host "Backend http://localhost:8000/docs  Frontend http://localhost:5173"
