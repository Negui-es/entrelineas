FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0t64 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python scripts/compile_translations.py \
    && DEBUG=true python manage.py collectstatic --noinput \
    && useradd --create-home --uid 10001 entrelineas \
    && mkdir -p /app/media /app/runtime/local-email \
    && chown -R entrelineas:entrelineas /app
USER entrelineas
EXPOSE 8000
CMD ["sh", "deploy/entrypoint.sh"]
