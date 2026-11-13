from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dataset_lifecycle_api import create_dataset_lifecycle_router
from app.dataset_lookup_api import get_dataset_runtime, router as dataset_lookup_router
from app.dataset_upload_api import create_upload_router
from app.local_security import LocalSecurityMiddleware

app = FastAPI(docs_url=None, redoc_url=None)
app.add_middleware(LocalSecurityMiddleware)
MAX_REQUEST_BODY_BYTES = 65_536  # Provisional transport limit.


class BoundedBodyRoute(APIRoute):
    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def bounded_handler(request: Request):
            body = bytearray()
            async for chunk in request.stream():
                if len(chunk) > MAX_REQUEST_BODY_BYTES - len(body):
                    return JSONResponse(status_code=413, content={
                        'error': {'code': 'REQUEST_TOO_LARGE', 'message': 'Request body is too large.'},
                    }, headers={'Cache-Control': 'no-store'})
                body.extend(chunk)

            async def receive():
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}

            return await original_handler(Request(request.scope, receive))

        return bounded_handler


request_router = APIRouter(route_class=BoundedBodyRoute)


class RequestInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    schema_version: Literal['1.0']
    client_request_id: str
    dataset_id: str = Field(strict=True, min_length=1, max_length=256)
    question: str = Field(strict=True, min_length=1, max_length=4096)

    @field_validator('client_request_id', 'dataset_id')
    @classmethod
    def uuid_string(cls, value: str) -> str:
        UUID(value)
        return value

    @field_validator('dataset_id', 'question')
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or '\x00' in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError('invalid text')
        return value


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={
        'error': {'code': 'INVALID_REQUEST', 'message': 'Invalid request.'},
    }, headers={'Cache-Control': 'no-store'})


@app.exception_handler(StarletteHTTPException)
async def invalid_body(request: Request, exc: StarletteHTTPException):
    if request.url.path == '/v1/requests' and request.method == 'POST' and exc.status_code == 400:
        return JSONResponse(status_code=422, content={
            'error': {'code': 'INVALID_REQUEST', 'message': 'Invalid request.'},
        })
    return await http_exception_handler(request, exc)


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok'}


@request_router.post('/v1/requests')
def create_request(payload: RequestInput, runtime=Depends(get_dataset_runtime)) -> JSONResponse:
    from app.request_api import create_request as create
    return create(payload, runtime)


@request_router.get('/v1/requests')
def request_history(limit: int = Query(default=20, ge=1, le=100),
                    cursor: str | None = Query(default=None, min_length=1, max_length=256),
                    runtime=Depends(get_dataset_runtime)):
    from app.request_api import history
    return history(runtime, limit, cursor)


@request_router.get('/v1/requests/{request_id}')
def request_status(request_id: UUID, runtime=Depends(get_dataset_runtime)):
    from app.request_api import status
    return status(runtime, request_id)


@request_router.post('/v1/requests/{request_id}/cancel')
def cancel_request(request_id: UUID, runtime=Depends(get_dataset_runtime)):
    from app.request_api import cancel
    return cancel(runtime, request_id)


@request_router.delete('/v1/requests/{request_id}')
def hide_request(request_id: UUID, runtime=Depends(get_dataset_runtime)):
    from app.request_api import hide
    return hide(runtime, request_id)


app.include_router(request_router)
app.include_router(dataset_lookup_router)
app.include_router(create_dataset_lifecycle_router(get_dataset_runtime))
app.include_router(create_upload_router(get_dataset_runtime))
