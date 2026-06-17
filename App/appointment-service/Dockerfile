FROM python:3.11-slim

WORKDIR /app

RUN mkdir -p /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV APP_ENV=development
ENV PORT=5001
ENV DB_PATH=/data/appointments.db
ENV DIRECTORY_SERVICE_BASE_URL=http://directory-service:5002
ENV NOTIFICATION_SERVICE_BASE_URL=http://notification-service:5003

EXPOSE 5001

CMD ["python", "app.py"]
