# --- Stage 1: Use an official Python runtime as a parent image ---
FROM python:3.9-slim-bullseye

# --- Set environment variables ---
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# --- Set the working directory in the container ---
WORKDIR /app

# --- Install dependencies ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "app.py"]
