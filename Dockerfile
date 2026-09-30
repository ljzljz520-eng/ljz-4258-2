FROM python:3.11-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt psycopg2-binary==2.9.9
COPY app ./app
COPY worker ./worker
COPY scripts ./scripts
COPY seed_data.py .
COPY frontend/dist ./frontend/dist
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
