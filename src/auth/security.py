"""Cookie-authenticated writes require a non-simple request header and trusted origin."""
from fastapi.responses import JSONResponse

from src.config import allowed_origins


async def mutation_guard(request, call_next):
    if request.url.path.startswith('/api/') and request.method in {'POST', 'PUT', 'DELETE', 'PATCH'}:
        origin = request.headers.get('origin')
        trusted = set(allowed_origins()) | {str(request.base_url).rstrip('/')}
        if request.headers.get('X-Aurion-Request') != '1' or (origin and origin not in trusted):
            return JSONResponse({'detail': 'Untrusted request origin or missing CSRF header.'}, status_code=403)
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response
