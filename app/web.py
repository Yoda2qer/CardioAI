"""Шаблоны и общие помощники для страниц."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .content import get_course
from .security import csrf_token

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

templates = Jinja2Templates(directory=APP_DIR / "templates")


def local_time(value: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """В базе время хранится в UTC; показываем в часовом поясе сервера."""
    if value is None:
        return "—"
    return value.replace(tzinfo=timezone.utc).astimezone().strftime(fmt)


def plural_word(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение: 1 урок, 2 урока, 5 уроков."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def plural(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {plural_word(n, one, few, many)}"


def static_url(path: str) -> str:
    """Адрес статического файла с меткой времени изменения, чтобы браузер не держал старую версию."""
    try:
        version = int((STATIC_DIR / path).stat().st_mtime)
    except OSError:
        version = 0
    return f"/static/{path}?v={version}"


templates.env.filters["local_time"] = local_time
templates.env.globals.update(plural=plural, plural_word=plural_word, static_url=static_url)


def render(request: Request, name: str, status_code: int = 200, **context):
    context.setdefault("user", getattr(request.state, "user", None))
    context.update(
        csrf_token=csrf_token(request),
        settings=get_settings(),
        course=get_course(),
    )
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def flash(request: Request, message: str, kind: str = "info") -> None:
    request.session.setdefault("flash", []).append({"message": message, "kind": kind})


def pop_flashes(request: Request) -> list[dict]:
    return request.session.pop("flash", [])


templates.env.globals["pop_flashes"] = pop_flashes

# Макросы иконок доступны во всех шаблонах, включая подключаемые через include.
_icons = templates.env.get_template("_icons.html").module
templates.env.globals.update(icon=_icons.icon, logo=_icons.logo)
