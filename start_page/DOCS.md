# Start Page

Every home service on one page, with live status from Uptime Kuma.

## What it serves

| Path | Content |
|---|---|
| `/` | The page: grouped link cards, a filter box, a theme toggle (dark by default, the choice kept in the browser). |
| `/services.json` | The cards, built from the options at start. |
| `/status.json` | Uptime Kuma's verdict for each monitor a card names, refreshed every `status_interval` seconds. |
| `/healthz` | `ok`, for the Supervisor watchdog. |

Reachable two ways, same server:

| Way | Where |
|---|---|
| Sidebar | Home Assistant, Start (ingress; needs a Home Assistant login). Cards open in a new tab, because the ingress frame allows popups and not top navigation. |
| Port | `http://<home assistant>:8090/` on the LAN, or as the origin for a tunnel hostname. Cards open in the same tab. |

The port has no login of its own; a login in front of it (Cloudflare Access, a reverse proxy) covers use beyond the LAN. The Uptime Kuma key stays in the add-on; `status.json` carries only the names and verdicts of monitors on cards.

## Options

| Option | Default | Effect |
|---|---|---|
| `title` | Home | Brand text and browser title. |
| `tagline` | start here | The small line under the title. |
| `lede` | | The paragraph above the cards. Empty hides it. |
| `uptime_kuma_url` | | Base URL of Uptime Kuma as the add-on reaches it, for example `http://homeassistant.local:3001`. Empty: no dots. |
| `uptime_kuma_api_key` | | An API key from Uptime Kuma, Settings, API Keys. |
| `uptime_kuma_verify_tls` | true | On an `https` URL the key is sent only to a certificate that verifies. Off accepts any certificate. |
| `uptime_kuma_ca_file` | | A CA certificate file under `/ssl` (mapped read-only) that signed Uptime Kuma's certificate. Empty uses the system store. |
| `status_interval` | 30 | Seconds between status reads, 10 to 600. |
| `services` | one example | The cards. |

Each service:

| Field | Required | Meaning |
|---|---|---|
| `group` | yes | Section heading. Sections appear in the order their first card does. |
| `name` | yes | Card title. |
| `url` | yes | Absolute `http` or `https` URL. |
| `description` | no | Second line on the card. |
| `monitor` | no | The monitor's name in Uptime Kuma, exactly as shown there. Gives the card a dot. |

```yaml
services:
  - group: Home
    name: Home Assistant
    url: https://homeassistant.local:8123
    description: The house
    monitor: Home Assistant
  - group: Elsewhere
    name: Cloudflare
    url: https://dash.cloudflare.com
```

A card with no name, a relative URL or a URL already on the page is left off and listed at the foot of the page and in the log.

## Dots

| Dot | Meaning |
|---|---|
| green | Uptime Kuma reports the monitor up. |
| red | down. |
| amber | pending or in maintenance. |
| grey | no `monitor` on the card, or no monitor of that name in Uptime Kuma (the tooltip says which). |
| dimmed | Uptime Kuma could not be read; the last verdict is shown and the footer says since when. |

The tooltip carries the response time and the check time. The browser probes nothing itself: a page served over HTTPS cannot reach plain-HTTP LAN services, and Uptime Kuma is the one verdict.

## Changing the cards

Settings, Add-ons, Start Page, Configuration, then Restart. The server reads the options once at start.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Every dot grey, footer says no Uptime Kuma configured | `uptime_kuma_url` empty | Set it and restart. |
| Footer says unreachable, HTTP 401 | Wrong or revoked key | Make a new key in Uptime Kuma; an existing key cannot be read back. |
| Footer says unreachable, connection refused | URL wrong for the add-on's network | Use the host's LAN address and Uptime Kuma's host port, not `localhost`. |
| One card grey, tooltip names the monitor | The name differs from Uptime Kuma's | Copy the monitor name exactly; it is case-sensitive. |
| Card missing | It was dropped as invalid | Read the foot of the page or the add-on log. |
