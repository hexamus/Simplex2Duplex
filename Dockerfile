# Base Alpine + Python officiel : beaucoup moins de paquets système qu'une
# Debian slim, et des bibliothèques (tesseract, libxml2, libtiff…) plus récentes.
# Pillow, pikepdf et ocrmypdf viennent de PyPI (roues musllinux à jour).
FROM python:3.13-alpine

ARG APP_VERSION=dev

LABEL org.opencontainers.image.title="Simplex2Duplex" \
      org.opencontainers.image.description="Assemble automatiquement deux PDF (rectos + versos) en un PDF recto-verso — remplaçant de pdfcollate" \
      org.opencontainers.image.source="https://github.com/hexamus/Simplex2Duplex" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${APP_VERSION}"

COPY requirements.txt /tmp/requirements.txt

# - apk upgrade : applique les correctifs publiés depuis la création de l'image de base.
# - tesseract + ghostscript + pngquant : moteurs utilisés par ocrmypdf.
# - poppler-utils : pdftoppm, rendu basse résolution pour la détection des pages blanches.
# - pip est désinstallé à la fin : inutile à l'exécution, et ses dépendances
#   vendorisées (urllib3, msgpack, setuptools) remontent dans les scanners de CVE.
RUN apk upgrade --no-cache \
 && apk add --no-cache \
      tesseract-ocr \
      tesseract-ocr-data-fra \
      tesseract-ocr-data-eng \
      ghostscript \
      pngquant \
      poppler-utils \
      tzdata \
 && pip install --no-cache-dir --upgrade -r /tmp/requirements.txt \
 && pip uninstall -y pip \
 && rm -rf /tmp/requirements.txt \
           /usr/local/lib/python3.*/ensurepip \
           /root/.cache

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
  CMD find /tmp/simplex2duplex.heartbeat -mmin -3 | grep -q . || exit 1

ENTRYPOINT ["python3", "/app/collate.py"]
CMD ["watch"]
