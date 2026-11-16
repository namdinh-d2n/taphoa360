"""Bound request bodies before JSON parsing, including chunked requests."""
from starlette.responses import JSONResponse


class RequestBodyLimit:
    def __init__(self, app, max_bytes, path_limits=None):
        self.app, self.max_bytes = app, max_bytes
        self.path_limits = path_limits or {}

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] in {'GET', 'HEAD', 'OPTIONS'}:
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        limit = self.path_limits.get(scope.get('path'), self.max_bytes)
        try:
            length = int(headers.get(b'content-length', b'0'))
        except ValueError:
            return await JSONResponse({'detail': 'Content-Length không hợp lệ'}, 400)(scope, receive, send)
        if length < 0 or length > limit:
            return await self.reject(scope, receive, send, limit)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > limit:
                return await self.reject(scope, receive, send, limit)
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)

    async def reject(self, scope, receive, send, limit):
        message = f'Ảnh tải lên quá lớn (tối đa {limit//1024//1024} MB)' if limit > self.max_bytes else 'Yêu cầu quá lớn (tối đa 1 MB)'
        await JSONResponse({'detail': message}, 413)(scope, receive, send)
