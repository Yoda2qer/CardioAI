# Образ платформы CardioAI для размещения на сервере. Подробности — в INSTALL.md.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/cardioai

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY content content
COPY manage.py .

# База SQLite и ключ сессий хранятся в instance/ — подключите сюда том, чтобы они пережили обновление.
RUN useradd --create-home --uid 1000 cardioai \
    && mkdir instance \
    && chown cardioai instance
USER cardioai
VOLUME ["/srv/cardioai/instance"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

# Прокси-заголовки (X-Forwarded-*) принимаются от обратного прокси, который стоит перед контейнером.
CMD ["python", "manage.py", "run", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips", "*"]
