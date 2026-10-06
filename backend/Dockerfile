# Django API for socialNET, served by Gunicorn.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.*

COPY . .
RUN useradd --create-home app && mkdir -p /app/data && chown -R app /app
USER app

EXPOSE 8500

# Migrate, load the demo dataset when DEMO_DATA=1, then serve.
CMD ["sh", "-c", "python manage.py migrate --noinput && if [ \"$DEMO_DATA\" = \"1\" ]; then python manage.py seed_data; fi && gunicorn config.wsgi --bind 0.0.0.0:8500 --workers 3"]
