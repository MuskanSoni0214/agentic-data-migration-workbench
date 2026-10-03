FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /data
COPY backend backend
COPY frontend frontend
COPY tests tests
ENV DATABASE_URL=sqlite:////data/migration.db MOCK_AI=true MAX_SAMPLE_SIZE=50
EXPOSE 8000
CMD ["uvicorn","backend.main:app","--host","0.0.0.0","--port","8000"]
