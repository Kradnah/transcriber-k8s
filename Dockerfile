FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp

WORKDIR /srv

COPY requirements.txt requirements-worker.txt ./
RUN pip install -r requirements-worker.txt

COPY app ./app

# Non-root user; Kubernetes enforces runAsNonRoot with the same UID.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001

EXPOSE 8000

# Same image runs both roles: the API (default) and the worker (python -m app.worker).
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
