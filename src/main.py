"""FastAPI application assembly.

Run with: python -m uvicorn src.main:app --host 127.0.0.1
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from src.api.routes import router
from src.api.auth_routes import router as auth_router
from src.api.household_routes import router as household_router
from src.api.routes import public_router
from src.auth.security import mutation_guard
from src.config import ROOT, allowed_origins


app = FastAPI(title='Quintrion', version='1.0.0')
origins = allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE'],
    allow_headers=['Content-Type', 'X-Aurion-Request', 'X-Household-ID'],
    allow_credentials=True,
)


app.middleware('http')(mutation_guard)


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
app.include_router(public_router)
app.include_router(auth_router)
app.include_router(household_router)

dist = ROOT / 'frontend' / 'dist'
if dist.is_dir():
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='web-assets')
    if (dist / 'brand').is_dir():
        app.mount('/brand', StaticFiles(directory=dist / 'brand'), name='brand-assets')

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(dist / 'index.html', headers={'Cache-Control': 'no-store'})

    @app.get('/{web_path:path}', include_in_schema=False)
    def web_page(web_path: str):
        # Browser deep links use the same React entry point; unknown API paths
        # and missing assets must retain a real 404 rather than returning HTML.
        if web_path == 'api' or web_path.startswith(('api/', 'assets/')):
            return JSONResponse({'detail': 'Not found'}, status_code=404)
        if web_path in {'favicon.ico', 'brand/quintrion_favicon.ico'}:
            return FileResponse(dist / 'brand' / 'quintrion_favicon.ico')
        return index()
