# Web app + Selenium scraper in one image (Chromium and its driver from Debian, versions always match).
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium chromium-driver fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*
ENV CHROME_BINARY=/usr/bin/chromium CHROMEDRIVER_PATH=/usr/bin/chromedriver GMCI_HEADLESS=1 \
    GMCI_DATA_DIR=/data PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
VOLUME /data
EXPOSE 8000
# One worker keeps background scrape jobs and the CAPTCHA pause in a single process; threads serve requests.
CMD gunicorn app:app --workers 1 --threads 8 --timeout 300 --bind 0.0.0.0:$PORT
