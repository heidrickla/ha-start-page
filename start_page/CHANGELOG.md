# Changelog

## 0.2.0

- Uptime Kuma's certificate is verified on an `https` URL before the key is sent: `uptime_kuma_ca_file` (a file under `/ssl`, mapped read-only) or the system store; `uptime_kuma_verify_tls` off accepts any certificate.
- `/status.json` carries the monitors the cards name, and no others.

## 0.1.0

- First release: grouped link cards from the add-on options, filter, theme toggle, ingress panel and host port 8090, status dots read from Uptime Kuma's `/metrics` with an API key.
- Cards open in a new tab when the page is framed by Home Assistant ingress, and in the same tab at top level.
