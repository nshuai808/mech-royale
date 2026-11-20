# Built by the scorer on linux/amd64 with network on (10 min limit, repo <= 20 MB).
# The match runs it with no network, a read-only root (writable /tmp, 64 MB), 1 CPU, 512 MB,
# as uid 65534, with the map mounted read-only at /arena.
# Base image pinned by digest so finalist rebuilds are identical.
FROM python:3.13.18-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# If you add dependencies: put pinned versions in requirements.txt and uncomment.
# Installs system-wide (not --user), so uid 65534 can import them.
# COPY requirements.txt /bot/requirements.txt
# RUN pip install --no-cache-dir -r /bot/requirements.txt

WORKDIR /bot
COPY . .
ENTRYPOINT ["python3", "-u", "/bot/bot.py"]
