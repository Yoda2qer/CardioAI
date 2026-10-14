"""Служебные команды платформы CardioAI.

    python manage.py init-db          создать таблицы базы данных
    python manage.py create-admin     создать администратора (или повысить существующего пользователя)
    python manage.py create-invite    создать код приглашения
    python manage.py has-admin        код возврата 0, если администратор уже есть
    python manage.py run              запустить сервер
"""

import argparse
import getpass
import sys

from sqlalchemy import select


def _init_db() -> None:
    from app.db import init_db

    init_db()


def cmd_init_db(_args) -> int:
    _init_db()
    print("База данных готова.")
    return 0


def cmd_has_admin(_args) -> int:
    from app.db import SessionLocal
    from app.models import User

    _init_db()
    with SessionLocal() as db:
        return 0 if db.scalar(select(User.id).where(User.role == "admin")) else 1


def cmd_create_admin(args) -> int:
    from app.db import SessionLocal
    from app.models import User
    from app.routers.auth import EMAIL_RE, normalize_email
    from app.security import hash_password, password_problem

    _init_db()
    email = normalize_email(args.email or input("Email администратора: "))
    if not EMAIL_RE.match(email):
        print("Некорректный email.", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user and not args.password:
            user.role = "admin"
            db.commit()
            print(f"Пользователь {email} теперь администратор.")
            return 0

        name = args.name or (user.full_name if user else input("ФИО: ").strip())
        password = args.password
        while not password:
            password = getpass.getpass("Пароль (не короче 8 символов, буквы и цифры): ")
            problem = password_problem(password)
            if problem:
                print(problem)
                password = None
            elif getpass.getpass("Повторите пароль: ") != password:
                print("Пароли не совпадают.")
                password = None
        problem = password_problem(password)
        if problem:
            print(problem, file=sys.stderr)
            return 1
        if len(name) < 2:
            print("Укажите ФИО.", file=sys.stderr)
            return 1

        if user is None:
            user = User(email=email, full_name=name, password_hash=hash_password(password), role="admin")
            db.add(user)
        else:
            user.role = "admin"
            user.full_name = name
            user.password_hash = hash_password(password)
            user.session_version += 1
        db.commit()
    print(f"Администратор {email} создан.")
    return 0


def cmd_create_invite(args) -> int:
    from app.db import SessionLocal
    from app.models import InviteCode
    from app.routers.admin import generate_invite_code

    _init_db()
    code = args.code or generate_invite_code()
    with SessionLocal() as db:
        if db.scalar(select(InviteCode.id).where(InviteCode.code == code)):
            print(f"Код {code} уже существует.", file=sys.stderr)
            return 1
        db.add(InviteCode(code=code, note=args.note, max_uses=args.max_uses))
        db.commit()
    print(f"Код приглашения: {code}")
    return 0


def cmd_run(args) -> int:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        proxy_headers=True,
        forwarded_allow_ips=args.forwarded_allow_ips,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Служебные команды CardioAI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="создать таблицы базы данных").set_defaults(func=cmd_init_db)
    sub.add_parser("has-admin", help="проверить, есть ли администратор").set_defaults(func=cmd_has_admin)

    admin = sub.add_parser("create-admin", help="создать администратора")
    admin.add_argument("--email")
    admin.add_argument("--name")
    admin.add_argument("--password", help="если не указан, будет запрошен скрытым вводом")
    admin.set_defaults(func=cmd_create_admin)

    invite = sub.add_parser("create-invite", help="создать код приглашения")
    invite.add_argument("--code", help="если не указан, будет сгенерирован")
    invite.add_argument("--note", default="")
    invite.add_argument("--max-uses", type=int, default=None, help="лимит регистраций по коду")
    invite.set_defaults(func=cmd_create_invite)

    run = sub.add_parser("run", help="запустить сервер")
    run.add_argument("--host", default="127.0.0.1", help="0.0.0.0 — принимать подключения из сети")
    run.add_argument("--port", type=int, default=8000)
    run.add_argument("--reload", action="store_true", help="перезапуск при изменении кода (для разработки)")
    run.add_argument("--forwarded-allow-ips", default="127.0.0.1")
    run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
