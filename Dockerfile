# Standard image: Cloud Run jobs & services, Kubernetes, ECS, plain docker run.
#
# The Playwright base ships the matching browser build and every system library
# Chromium needs — reproducing that on a slim base is a long, brittle apt list.
#
# `noble` (Ubuntu 24.04, Python 3.12), not `jammy` (22.04, Python 3.10): this
# package needs >= 3.11 for datetime.UTC.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    GRS_DATA_DIR=/data

WORKDIR /app

# Dependency layer first so source edits do not re-resolve the world.
# LICENSE is required: pyproject declares `license = { file = "LICENSE" }`.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && playwright install chromium

COPY schemas ./schemas

# `pwuser` ships with the base image. /data holds the SQLite queue and the
# persistent browser profile; mount a volume over it to keep them between runs.
RUN mkdir -p /data && chown -R pwuser:pwuser /data /app
USER pwuser
VOLUME ["/data"]

# Cloud Run services inject PORT; `serve` honours it. Jobs ignore it.
ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["grscraper"]
# Override with `serve` for a service, or any other subcommand.
CMD ["sync"]
