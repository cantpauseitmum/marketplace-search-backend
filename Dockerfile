FROM python:3.12-slim

WORKDIR /app

# Kopiowanie plików backendu
COPY . /app

# Zmienne środowiskowe
ENV PORT=8000
ENV HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Uruchomienie serwera
CMD ["python3", "server.py"]
