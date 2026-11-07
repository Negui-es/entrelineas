#!/bin/sh
set -eu
python manage.py migrate --noinput
python manage.py createcachetable
exec gunicorn entrelineas.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 2 --timeout 60 --access-logfile - --error-logfile -
