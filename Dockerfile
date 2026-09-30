# MaxPlan — image du dashboard (Python stdlib, zéro dépendance externe)
FROM python:3.12-slim

# Réglages par défaut (surchargeables via docker-compose / -e)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MAXFINDER_HOST=0.0.0.0 \
    PORT=8765 \
    DATA_DIR=/data

WORKDIR /app

# Code applicatif (le .dockerignore exclut .env, caches, .git, etc.)
COPY . /app

# Utilisateur non-root + répertoire de données persistant
RUN useradd -m -u 10001 appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8765
VOLUME ["/data"]

# Sonde de santé : interroge /healthz (aucun appel réseau externe)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/healthz',timeout=3).status==200 else 1)"

CMD ["python", "server.py"]
