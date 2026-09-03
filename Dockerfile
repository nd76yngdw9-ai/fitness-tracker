FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ordner für die persistente Datenbank (wird per Volume gemountet)
RUN mkdir -p /data
ENV DB_PFAD=/data/tracker.db

EXPOSE 5000

CMD ["python", "app.py"]
