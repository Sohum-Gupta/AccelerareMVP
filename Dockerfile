# App image: the deploy unit. Built once in CI, run on the server as the web
# container (and later the worker, with a different command).

FROM python:3.12-slim

# uv, copied from its official image and pinned to the version used locally.
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

# PYTHONUNBUFFERED: logs appear immediately in `docker logs`.
# UV_COMPILE_BYTECODE: faster container start.
# UV_LINK_MODE=copy: avoids a harmless warning when the cache is on another disk.
# DJANGO_SETTINGS_MODULE: this image is always production. manage.py defaults to
# local settings on a laptop, so without this, `docker compose exec web python
# manage.py migrate` on the server would silently run with DEBUG on.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first. This layer is cached until pyproject.toml or uv.lock
# change, so code-only changes rebuild in seconds.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Then the application code.
COPY . .

# Gather static files for WhiteNoise. Loading settings needs SECRET_KEY and
# DATABASE_URL, so throwaway values are set for this one command only. They are
# not stored in the image; real values arrive at container start.
RUN SECRET_KEY=build-only-not-a-secret \
    DATABASE_URL=postgres://build:build@localhost:5432/build \
    python manage.py collectstatic --noinput

# Do not run as root inside the container.
RUN useradd --system --no-create-home app && chown -R app:app /app
USER app

EXPOSE 8000

# config/wsgi.py defaults to production settings. The server's compose file may
# override this command (for example, for the worker).
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "2", "--no-control-socket"]
