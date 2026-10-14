import mimetypes
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .content import get_course
from .db import SessionLocal, init_db
from .models import User
from .routers import admin, auth, course, quiz
from .security import RedirectTo
from .web import STATIC_DIR, render

# Офлайн-копия Pyodide отдаётся с сайта: браузер исполняет модули и WebAssembly
# только с правильными типами, а в реестре Windows они могут отсутствовать.
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")

ERROR_TITLES = {
    403: "Доступ закрыт",
    404: "Страница не найдена",
    429: "Слишком много запросов",
}


def _content_security_policy() -> str:
    """Разрешает скрипты только с самого сайта и с адреса, откуда грузится Pyodide."""
    parsed = urlsplit(get_settings().pyodide_base_url)
    cdn = f" {parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src 'self' 'wasm-unsafe-eval'{cdn}",
            f"connect-src 'self'{cdn}",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "worker-src 'self' blob:",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ]
    )


def create_app() -> FastAPI:
    settings = get_settings()
    init_db()
    get_course()  # ошибки в содержимом курса должны останавливать запуск, а не всплывать у слушателя

    app = FastAPI(title="CardioAI", docs_url=None, redoc_url=None, openapi_url=None)
    csp = _content_security_policy()

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="cardioai_session",
        max_age=settings.session_days * 86400,
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(RedirectTo)
    async def redirect_handler(_request: Request, exc: RedirectTo):
        return RedirectResponse(exc.url, status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        # Обработчик может сработать до того, как зависимости загрузили пользователя.
        if not hasattr(request.state, "user") and request.session.get("uid"):
            with SessionLocal() as db:
                request.state.user = db.get(User, request.session["uid"])
        return render(
            request,
            "error.html",
            status_code=exc.status_code,
            code=exc.status_code,
            title=ERROR_TITLES.get(exc.status_code, "Что-то пошло не так"),
            detail=exc.detail if exc.status_code != 404 else "Возможно, ссылка устарела или в адресе опечатка.",
        )

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(course.router)
    app.include_router(quiz.router)
    app.include_router(admin.router)
    return app


app = create_app()
