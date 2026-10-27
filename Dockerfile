FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends binutils gdal-bin libgeos-c1v5 libproj25 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN /usr/local/bin/python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 1000 django

COPY --chown=django:django . .
USER django

EXPOSE 8000
CMD ["/usr/local/bin/python", "manage.py", "runserver", "0.0.0.0:8000"]
