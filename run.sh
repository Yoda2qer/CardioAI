#!/usr/bin/env sh
# Запуск платформы CardioAI в macOS и Linux. Подробности — в INSTALL.md.
# Параметры передаются серверу, например: ./run.sh --host 0.0.0.0 --port 8080
set -e
cd "$(dirname "$0")"

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "Python не найден. Установите Python 3.11 или новее и запустите скрипт снова." >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "Создаю виртуальное окружение .venv ..."
    "$PYTHON" -m venv .venv
fi
VENV_PY=.venv/bin/python

echo "Проверяю зависимости ..."
"$VENV_PY" -m pip install --disable-pip-version-check --quiet -r requirements.txt

"$VENV_PY" manage.py init-db

if ! "$VENV_PY" manage.py has-admin; then
    echo
    echo "Первый запуск: создайте учётную запись администратора."
    "$VENV_PY" manage.py create-admin
    "$VENV_PY" manage.py create-invite --note "Первый код приглашения"
    echo "Передайте этот код слушателям. Новые коды можно создавать в разделе «Слушатели»."
fi

echo
echo "Запускаю сервер. Адрес сайта — в строке «Uvicorn running on» ниже (по умолчанию http://localhost:8000)."
echo "Остановить сервер — Ctrl+C."
exec "$VENV_PY" manage.py run "$@"
