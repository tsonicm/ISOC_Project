FROM python:3.11-slim

WORKDIR /app

RUN mkdir -p /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV APP_ENV=development
ENV PORT=5003
ENV DB_PATH=/data/notifications.db

EXPOSE 5003

CMD ["python", "app.py"]
