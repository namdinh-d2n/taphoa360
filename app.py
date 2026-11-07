"""Tap hoa 360: authenticated retail operations, POS and staff management."""
from contextlib import asynccontextmanager
import logging
import sqlite3
import config
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn
from config import BASE_DIR, HOST, PORT, RELOAD
from retail import auth, api, sales
from retail.database import migrate, reading, SCHEMA_VERSION
from retail.middleware import RequestBodyLimit
from retail.access import ROLE_PORTALS, home_for, may_open

@asynccontextmanager
async def lifespan(app):
    migrate()
    if config.PRODUCTION and auth.setup_status()['required'] and len(config.SETUP_TOKEN) < 32:
        raise RuntimeError('Set SETUP_TOKEN to at least 32 random characters before starting an unconfigured production store.')
    yield

app = FastAPI(title='Tạp hóa 360', version='3.1.0', lifespan=lifespan,
              docs_url='/docs' if config.ENABLE_DOCS else None,
              redoc_url=None, openapi_url='/openapi.json' if config.ENABLE_DOCS else None)
app.add_middleware(RequestBodyLimit, max_bytes=config.MAX_REQUEST_BYTES)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)
app.include_router(auth.router)
app.include_router(api.router)
app.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')
templates = Jinja2Templates(directory=BASE_DIR / 'templates')

@app.middleware('http')
async def response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(self)'
    if request.url.path not in {'/docs', '/openapi.json'}:
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    if config.PRODUCTION:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    if not request.url.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store'
    else:
        response.headers['Cache-Control'] = 'no-cache'
    return response


@app.get('/health/live', include_in_schema=False)
def liveness():
    return {'status': 'ok'}


@app.get('/health/ready', include_in_schema=False)
def readiness():
    try:
        with reading() as conn:
            version = conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
            conn.execute('SELECT id FROM users LIMIT 1').fetchone()
        if version != SCHEMA_VERSION:
            raise sqlite3.OperationalError('Unexpected schema version')
    except sqlite3.Error:
        return JSONResponse({'status': 'unavailable'}, status_code=503)
    return {'status': 'ok'}

@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error(request, exc):
    logging.getLogger('taphoa').warning('Integrity error: %s', exc)
    return JSONResponse({'detail': 'Dữ liệu bị trùng hoặc không còn hợp lệ. Hãy tải lại và kiểm tra.'}, status_code=409)

@app.exception_handler(sqlite3.OperationalError)
async def database_error(request, exc):
    logging.getLogger('taphoa').exception('Database operation failed', exc_info=exc)
    return JSONResponse({'detail': 'Không thể truy cập dữ liệu lúc này. Vui lòng thử lại.'}, status_code=503)

@app.get('/login', response_class=HTMLResponse, include_in_schema=False)
@app.get('/login/{role}', response_class=HTMLResponse, include_in_schema=False)
@app.get('/setup', response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, role: str | None = None):
    if role is not None and role not in ROLE_PORTALS:
        raise HTTPException(404, 'Không tìm thấy trang đăng nhập')
    setup = auth.setup_status()['required']
    if request.url.path == '/setup' and not setup:
        return RedirectResponse('/login', 303)
    selected = 'owner' if setup else role
    return templates.TemplateResponse(request=request, name='login.html', context={
        'setup': setup, 'role': selected, 'role_info': ROLE_PORTALS.get(selected),
        'roles': ROLE_PORTALS, 'setup_token_required': bool(config.SETUP_TOKEN),
    })


@app.get('/register', response_class=HTMLResponse, include_in_schema=False)
@app.get('/register/{role}', response_class=HTMLResponse, include_in_schema=False)
def register_page(request: Request, role: str | None = None):
    if role is not None and role not in ROLE_PORTALS:
        raise HTTPException(404, 'Không tìm thấy vai trò đăng ký')
    if auth.setup_status()['required']:
        return RedirectResponse('/setup', 303)
    return templates.TemplateResponse(request=request, name='register.html', context={
        'role': role, 'role_info': ROLE_PORTALS.get(role), 'roles': ROLE_PORTALS,
    })

@app.get('/receipt/{ident}', response_class=HTMLResponse, include_in_schema=False)
def receipt(request: Request, ident: int):
    user = auth.current_user(request)
    auth.require('cashier', 'shipper')(user)
    with reading() as conn:
        order = sales.order_detail(conn, ident, user)
    return templates.TemplateResponse(request=request, name='receipt.html', context={'order': order})

PAGES = {'/': 'dashboard', '/index': 'dashboard', '/index.php': 'dashboard', '/pos': 'pos', '/orders': 'orders', '/orders.php': 'orders', '/warehouse': 'inventory', '/warehouse.php': 'inventory', '/store_map': 'map', '/store-map': 'map', '/store_map.php': 'map', '/hr': 'hr', '/hr.php': 'hr', '/products': 'products', '/customers': 'customers', '/suppliers': 'suppliers', '/cash': 'cash', '/reports': 'reports', '/suggestions': 'suggestions', '/settings': 'settings'}
PAGES.update({'/owner': 'owner_portal', '/cashier': 'cashier_portal', '/inventory': 'inventory_portal', '/shipper': 'shipper_portal'})

def page(request: Request):
    if auth.setup_status()['required']:
        return RedirectResponse('/setup', 303)
    try:
        user = auth.current_user(request)
    except HTTPException:
        portal_role = request.url.path.lstrip('/')
        return RedirectResponse('/login/' + portal_role if portal_role in ROLE_PORTALS else '/login', 303)
    selected_page = PAGES[request.url.path]
    if selected_page == 'dashboard' or not may_open(user['role'], selected_page):
        return RedirectResponse(home_for(user['role']), 303)
    return templates.TemplateResponse(request=request, name='retail.html', context={
        'page': selected_page, 'user': user, 'role_info': ROLE_PORTALS[user['role']],
    })

for path in PAGES:
    app.add_api_route(path, page, methods=['GET'], response_class=HTMLResponse, include_in_schema=False)

if __name__ == '__main__':
    uvicorn.run('app:app', host=HOST, port=PORT, reload=RELOAD)
