from typing import Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

app = FastAPI()
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
                    })
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

    @field_validator('client_request_id')
    @classmethod
    def uuid_string(cls, value: str) -> str:
        UUID(value)
        return value

    @field_validator('dataset_id', 'question')
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('blank')
        return value


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={
        'error': {'code': 'INVALID_REQUEST', 'message': 'Invalid request.'},
    })


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
def create_request(payload: RequestInput) -> JSONResponse:
    return JSONResponse(status_code=503, content={
        'error': {'code': 'EXECUTION_UNAVAILABLE', 'message': 'Request processing is unavailable.'},
    })


app.include_router(request_router)
