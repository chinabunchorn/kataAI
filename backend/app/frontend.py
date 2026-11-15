"""Serve the compiled UI behind the unchanged loopback security middleware."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, dist: Path) -> None:
    # Mount only public build assets, never the repository or dataset root.
    if (dist / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='frontend-assets')

    @app.get('/', include_in_schema=False)
    def index():
        if not (dist / 'index.html').is_file():
            return JSONResponse({'error': {'code': 'FRONTEND_NOT_BUILT',
                                          'message': 'Run npm ci && npm run build in frontend.'}},
                                status_code=503)
        return FileResponse(dist / 'index.html', headers={'Cache-Control': 'no-store'})

    @app.get('/favicon.svg', include_in_schema=False)
    def favicon():
        if not (dist / 'favicon.svg').is_file():
            return JSONResponse({}, status_code=404)
        return FileResponse(dist / 'favicon.svg')
