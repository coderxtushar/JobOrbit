# JobOrbit API: the FastAPI backend, built for the hosted public demo.
#
# The image carries the API only. Auto-apply needs a visible Chrome window for CAPTCHAs, so
# it is not part of a hosted container; the demo refuses auto-apply runs anyway.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The dashboard (Streamlit) and test tools are not needed to serve the API.
COPY requirements.txt .
RUN grep -vE '^(streamlit|pytest|pytest-cov)==' requirements.txt > requirements.api.txt \
 && pip install -r requirements.api.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

RUN useradd --create-home --uid 10001 joborbit && mkdir -p var && chown -R joborbit var
USER joborbit

# Binding beyond loopback makes the API refuse to start without JA_API_TOKEN (app/config.py).
ENV JA_API_HOST=0.0.0.0
EXPOSE 8000

# Render (and most hosts) pass the port in $PORT. Migrations run first; in demo mode the
# API seeds its fictional data on startup, so an empty disk is fine.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
