FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py .

# run as a non-root user
RUN useradd --create-home app
USER app

EXPOSE 8000
# 1 worker on purpose: small machine, and slowapi's in-memory counters stay consistent
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
