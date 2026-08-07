FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd -r oberon && useradd -r -g oberon -d /app oberon \
    && mkdir -p /data && chown -R oberon:oberon /app /data
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=oberon:oberon app ./app
USER oberon
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -m app.healthcheck
CMD ["python", "-m", "app.main"]
