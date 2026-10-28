FROM debian:trixie-slim

ARG APP_VERSION=dev

LABEL org.opencontainers.image.title="2-1_Scan" \
      org.opencontainers.image.description="Assemble automatiquement deux PDF (rectos + versos) en un PDF recto-verso — remplaçant de pdfcollate" \
      org.opencontainers.image.source="https://github.com/hexamus/2-1_Scan" \
      org.opencontainers.image.version="${APP_VERSION}"

# ocrmypdf apporte python3, pikepdf, Pillow, tesseract et ghostscript.
# poppler-utils : rendu basse résolution pour la détection des pages blanches.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ocrmypdf \
      tesseract-ocr-fra \
      tesseract-ocr-eng \
      pngquant \
      poppler-utils \
      tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV APP_VERSION=${APP_VERSION} \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    TZ=Europe/Paris \
    INPUT_DIR=/input \
    OUTPUT_DIR=/output

COPY collate.py /app/collate.py
RUN chmod 0755 /app/collate.py

WORKDIR /app
VOLUME ["/input", "/output"]

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
  CMD find /tmp/2-1_scan.heartbeat -mmin -3 | grep -q . || exit 1

ENTRYPOINT ["python3", "/app/collate.py"]
CMD ["watch"]
