FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
# Pinned lock so scikit-learn matches the version recorded in the model manifest (loader refuses mismatches).
COPY requirements-lock.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
# Evaluation summaries (committed JSON). Trained models are mounted read-only at /app/ml/artifacts.
COPY docs/report/results /app/docs/report/results
RUN mkdir -p /data /app/ml/artifacts
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m app.db.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
