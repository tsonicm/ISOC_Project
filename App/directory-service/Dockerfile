FROM python:3.11-slim

WORKDIR /app

RUN mkdir -p /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV APP_ENV=development
ENV PORT=5002
ENV DB_PATH=/data/directory.db

EXPOSE 5002

CMD ["python", "app.py"]
