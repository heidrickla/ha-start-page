# Changelog

## 0.3.0

- Discovered cards: Home Assistant and each running app with a web interface get a card without typing, kept up to date every five minutes. `discover_cards` turns them off; a card under `services` with the same name replaces a discovered one. The app reads the Supervisor with the default role (`hassio_api`).
- An empty `uptime_kuma_url` finds the Uptime Kuma app on the same Home Assistant.
- The footer and the log say what is missing for status dots: no Uptime Kuma, or no API key.
- The page says how to add cards when it has none.
- `services` starts empty.
- The image builds from `ghcr.io/home-assistant/base:3.24` (Python 3.14) for every architecture from the `Dockerfile`; `build.yaml` is gone.
- A Docker health check replaces the `watchdog` URL; the Supervisor's watchdog follows it.
- The deprecated `advanced` key and the keys holding default values are gone from `config.yaml`; every option, including each field of `services`, has a translated name and description.

## 0.2.0

- Uptime Kuma's certificate is verified on an `https` URL before the key is sent: `uptime_kuma_ca_file` (a file under `/ssl`, mapped read-only) or the system store; `uptime_kuma_verify_tls` off accepts any certificate.
- `/status.json` carries the monitors the cards name, and no others.

## 0.1.0

- First release: grouped link cards from the add-on options, filter, theme toggle, ingress panel and host port 8090, status dots read from Uptime Kuma's `/metrics` with an API key.
- Cards open in a new tab when the page is framed by Home Assistant ingress, and in the same tab at top level.
