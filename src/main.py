"""FastAPI application assembly.

Run with: python -m uvicorn src.main:app --host 127.0.0.1
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from src.api.routes import router
from src.config import ROOT, allowed_origins


app = FastAPI(title='Portfolio Tracker', version='1.0.0')
origins = allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE'],
    allow_headers=['Content-Type'],
)


@app.middleware('http')
async def local_mutation_guard(request: Request, call_next):
    if request.method in {'POST', 'PUT', 'DELETE', 'PATCH'}:
        origin = request.headers.get('origin')
        allowed = set(origins) | {'http://localhost:8000', 'http://127.0.0.1:8000'}
        if origin and origin not in allowed:
            return JSONResponse({'detail': 'Origem não permitida.'}, status_code=403)
    return await call_next(request)


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return JSONResponse(
        {
            'detail': (
                'Banco indisponível ou operação não concluída. Verifique PostgreSQL '
                'e execute alembic upgrade head.'
            )
        },
        status_code=503,
    )


@app.exception_handler(ValueError)
async def calculation_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=422)


app.include_router(router)

dist = ROOT / 'frontend' / 'dist'
if dist.is_dir():
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='web-assets')

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(dist / 'index.html')
