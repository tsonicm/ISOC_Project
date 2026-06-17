FROM python:3.11-slim

WORKDIR /app

RUN mkdir -p /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV APP_ENV=development
ENV PORT=8080
ENV DB_PATH=/data/web.db
ENV SECRET_KEY=dev-secret-key-change-in-prod
ENV DIRECTORY_SERVICE_BASE_URL=http://directory-service:5002
ENV APPOINTMENT_SERVICE_BASE_URL=http://appointment-service:5001
ENV NOTIFICATION_SERVICE_BASE_URL=http://notification-service:5003

EXPOSE 8080

CMD ["python", "app.py"]
