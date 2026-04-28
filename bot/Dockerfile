FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m spacy download en_core_web_sm

COPY . .

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Create non-root user, give ownership of app + mounted volumes
RUN useradd -m -u 1001 botuser && chown -R botuser:botuser /app
USER botuser

ENTRYPOINT ["./entrypoint.sh"]
