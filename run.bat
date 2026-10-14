@echo off
rem Запуск платформы CardioAI в Windows. Подробности — в INSTALL.md.
rem Параметры передаются серверу, например: run.bat --host 0.0.0.0 --port 8080
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PYTHON="
where py >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON (
    where python >nul 2>nul && set "PYTHON=python"
)
if not defined PYTHON (
    echo Python не найден. Установите Python 3.11 или новее с сайта python.org,
    echo отметив пункт "Add python.exe to PATH", и запустите run.bat снова.
    goto :error
)

if not exist ".venv\Scripts\python.exe" (
    echo Создаю виртуальное окружение .venv ...
    %PYTHON% -m venv .venv || goto :error
)
set "VENV_PY=.venv\Scripts\python.exe"

echo Проверяю зависимости ...
"%VENV_PY%" -m pip install --disable-pip-version-check --quiet -r requirements.txt || goto :error

"%VENV_PY%" manage.py init-db || goto :error

"%VENV_PY%" manage.py has-admin
if errorlevel 1 (
    echo.
    echo Первый запуск: создайте учётную запись администратора.
    "%VENV_PY%" manage.py create-admin || goto :error
    "%VENV_PY%" manage.py create-invite --note "Первый код приглашения" || goto :error
    echo Передайте этот код слушателям. Новые коды можно создавать в разделе «Слушатели».
)

echo.
echo Запускаю сервер. Адрес сайта — в строке «Uvicorn running on» ниже (по умолчанию http://localhost:8000).
echo Остановить сервер — Ctrl+C.
"%VENV_PY%" manage.py run %*
goto :eof

:error
echo.
echo Запуск не удался. Решения типичных проблем — в INSTALL.md, раздел «Типичные ошибки».
pause
exit /b 1
