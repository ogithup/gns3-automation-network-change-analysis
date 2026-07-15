# Environment Guide

## Backend

- Python `3.11+`
- FastAPI backend on `http://127.0.0.1:8000`
- GNS3 local server reachable on `http://[::1]:3080` or configured `GNS3_SERVER_URL`

## Frontend

- Node.js `20+`
- Vite dev server on `http://127.0.0.1:5173`

## Required Local Commands

```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
uvicorn app.main:app --reload
```

```powershell
cd frontend
npm install
cmd /c npm run dev
```

## Optional Real GNS3 Validation

```powershell
$env:NETTWIN_RUN_REAL_GNS3="1"
$env:GNS3_SERVER_URL="http://[::1]:3080"
cd backend
pytest tests/test_real_gns3_optional.py -q
```
