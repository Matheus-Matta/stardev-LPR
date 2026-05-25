FROM bluenviron/mediamtx:latest AS mediamtx-bin

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libmagic1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# MediaMTX binary — used by the run_media_server management command
COPY --from=mediamtx-bin /mediamtx /usr/local/bin/mediamtx

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]

