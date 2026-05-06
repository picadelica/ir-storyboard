FROM python:3.11-slim

WORKDIR /app

# Install backend deps
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy code
COPY ir_storyboard /app/ir_storyboard
COPY backend       /app/backend
COPY schema.sql    /app/schema.sql

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
