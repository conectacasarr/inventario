# Simple Dockerfile for Flask app
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:5000", "--workers", "3"]
