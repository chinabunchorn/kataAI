import re
from dataclasses import dataclass

from starlette.responses import JSONResponse, Response


@dataclass(frozen=True)
class SecurityPolicy:
    host: str = '127.0.0.1:8000'
    origin: str = 'http://127.0.0.1:8000'

    def __post_init__(self):
        # Deliberately support only literal IPv4 loopback and explicit, canonical ports.
        for value, prefix in ((self.host, ''), (self.origin, 'http://')):
            if not isinstance(value, str):
                raise ValueError('Invalid local security configuration')
            match = re.fullmatch(re.escape(prefix) + r'127\.0\.0\.1:([1-9][0-9]{0,4})', value)
            if match is None or int(match.group(1)) > 65535:
                raise ValueError('Invalid local security configuration')


class LocalSecurityMiddleware:
    def __init__(self, app, policy=None):
        self.app = app
        self.policy = SecurityPolicy() if policy is None else policy
        if not isinstance(self.policy, SecurityPolicy):
            raise ValueError('Invalid local security configuration')

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
            return
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        def values(name):
            return [v for k, v in scope['headers'] if k.lower() == name]

        async def deny():
            response = JSONResponse({'error': {'code': 'FORBIDDEN', 'message': 'Request denied.'}}, status_code=403)
            await response(scope, receive, send)

        hosts, origins = values(b'host'), values(b'origin')
        origin = self.policy.origin.encode('ascii')
        if hosts != [self.policy.host.encode('ascii')] or len(origins) > 1 or (origins and origins != [origin]):
            await deny()
            return

        method = scope['method']
        requested_methods = values(b'access-control-request-method')
        requested_headers = values(b'access-control-request-headers')
        if method == 'OPTIONS' and (requested_methods or requested_headers):
            methods = {b'GET', b'HEAD', b'POST', b'PUT', b'PATCH', b'DELETE'}
            if origins != [origin] or len(requested_methods) != 1 or requested_methods[0] not in methods or len(requested_headers) > 1:
                await deny()
                return
            requested = [h.strip().lower() for h in requested_headers[0].split(b',')] if requested_headers else []
            if any(h not in {b'content-type', b'x-kataai-request'} for h in requested):
                await deny()
                return
            response = Response(status_code=204, headers={
                'Access-Control-Allow-Origin': self.policy.origin,
                'Access-Control-Allow-Methods': 'GET, HEAD, POST, PUT, PATCH, DELETE',
                'Access-Control-Allow-Headers': 'content-type, x-kataai-request',
                'Vary': 'Origin, Access-Control-Request-Method, Access-Control-Request-Headers',
            })
            await response(scope, receive, send)
            return

        if method not in ('GET', 'HEAD') and (origins != [origin] or values(b'x-kataai-request') != [b'1']):
            await deny()
            return

        async def cors_send(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                headers.append((b'vary', b'Origin'))
                if origins:
                    headers.append((b'access-control-allow-origin', origin))
                message = {**message, 'headers': headers}
            await send(message)

        await self.app(scope, receive, cors_send)
