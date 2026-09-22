FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY data/ ./data/
COPY --from=web /web/dist ./frontend/dist
CMD ["sh", "-c", "python -m alembic upgrade head && python -m src.instrument_catalog && python -m uvicorn src.main:app --host 0.0.0.0 --port 8000"]
