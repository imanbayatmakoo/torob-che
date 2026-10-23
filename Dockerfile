FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./backend/app
COPY frontend/web ./frontend/web
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir /app/backend"]
