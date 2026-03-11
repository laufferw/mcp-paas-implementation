FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python scripts/migrate.py 2>/dev/null || true
EXPOSE 8000
CMD ["python", "server.py"]
