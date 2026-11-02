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
# A new named volume takes its ownership from this directory, so collectstatic can write to it.
RUN mkdir -p /app/staticfiles && chown django:django /app/staticfiles
USER django

EXPOSE 8000
CMD ["gunicorn", "studysmart.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
