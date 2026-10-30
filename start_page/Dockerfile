FROM ghcr.io/home-assistant/base:3.24

SHELL ["/bin/ash", "-o", "pipefail", "-c"]

# The server is the Python standard library; nothing is pip-installed.
# hadolint ignore=DL3018
RUN apk add --no-cache python3 \
 && python3 -c "import http.server, ssl, urllib.request; print('python ok')"

WORKDIR /opt/start_page
COPY server.py ./
COPY www ./www
RUN python3 -m py_compile server.py

COPY run.sh /run.sh
RUN chmod +x /run.sh

ENV PYTHONUNBUFFERED=1

# Docker's health state is what the Supervisor's watchdog follows.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --start-interval=2s --retries=3 \
  CMD ["/bin/sh", "-c", "curl -fsS -o /dev/null http://127.0.0.1:8090/healthz || exit 1"]

CMD ["/run.sh"]

ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=dev
LABEL \
    io.hass.name="Start Page" \
    io.hass.description="Every home service on one page, with live status from Uptime Kuma" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="app" \
    io.hass.version="${BUILD_VERSION}" \
    maintainer="Lewis Heidrick" \
    org.opencontainers.image.title="Start Page" \
    org.opencontainers.image.description="Every home service on one page, with live status from Uptime Kuma" \
    org.opencontainers.image.vendor="Lewis Heidrick" \
    org.opencontainers.image.authors="Lewis Heidrick" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.url="https://github.com/heidrickla/ha-start-page" \
    org.opencontainers.image.source="https://github.com/heidrickla/ha-start-page" \
    org.opencontainers.image.documentation="https://github.com/heidrickla/ha-start-page/blob/main/start_page/DOCS.md" \
    org.opencontainers.image.version="${BUILD_VERSION}"
