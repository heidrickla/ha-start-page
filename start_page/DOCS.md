# Start Page

Every home service on one page, with live status from Uptime Kuma.

## Setup

1. Install and start the app.
2. Turn on Show in sidebar, then open Start.
3. For status dots, make an API key in Uptime Kuma (Settings, API Keys), paste it into Uptime Kuma API key on the Configuration tab, and restart the app.

Home Assistant and each running app with a web interface get a card on their own. Add your own cards under Services.

## What it serves

| Path | Content |
|---|---|
| `/` | The page: grouped link cards, a filter box, a theme toggle (dark by default, the choice kept in the browser). |
| `/services.json` | The cards: those under Services, then the discovered ones. |
| `/status.json` | Uptime Kuma's verdict for each monitor a card names, refreshed every `status_interval` seconds. |
| `/healthz` | `ok`, for the container health check the Supervisor's watchdog follows. |

Reachable two ways, same server:

| Way | Where |
|---|---|
| Sidebar | Home Assistant, Start (ingress; needs a Home Assistant login). Cards open in a new tab, because the ingress frame allows popups and not top navigation. |
| Port | `http://<home assistant>:8090/` on the LAN, or as the origin for a tunnel hostname. Cards open in the same tab. |

The Uptime Kuma key stays in the app; `status.json` carries only the names and verdicts of monitors on cards.

## Discovered cards

With Discover cards on, the app reads the Supervisor every five minutes and shows, in a group called Home Assistant:

| Card | Opens |
|---|---|
| Home Assistant | Home Assistant itself. |
| Each running app with ingress | The app's page in Home Assistant. |
| Each running app with a web UI port | The app's web UI on the host the page was opened from, as Open Web UI does. |

In the sidebar, Home Assistant's address is the one the page was opened on. On the port, it is the same host on Home Assistant's own port. A card under Services with the same name as a discovered card replaces it, for an address that differs from the worked-out one (a tunnel hostname, for example).

## Options

| Option | Default | Effect |
|---|---|---|
| `title` | Home | Brand text and browser title. |
| `tagline` | start here | The small line under the title. |
| `lede` | a short paragraph | The paragraph above the cards. Empty hides it. |
| `discover_cards` | true | Cards for Home Assistant and its running apps, as above. |
| `uptime_kuma_url` | | Base URL of Uptime Kuma as the app reaches it. Empty finds the Uptime Kuma app on this Home Assistant (its address on the internal network). |
| `uptime_kuma_api_key` | | An API key from Uptime Kuma, Settings, API Keys. Needed for status dots. |
| `uptime_kuma_verify_tls` | true | On an `https` URL the key is sent only to a certificate that verifies. Off accepts any certificate. |
| `uptime_kuma_ca_file` | | A CA certificate file under `/ssl` (mapped read-only) that signed Uptime Kuma's certificate. Empty uses the system store. |
| `status_interval` | 30 | Seconds between status reads, 10 to 600. |
| `services` | none | Cards of your own, shown before the discovered ones. |

Each service:

| Field | Required | Meaning |
|---|---|---|
| `group` | yes | Section heading. Sections appear in the order their first card does. |
| `name` | yes | Card title. |
| `url` | yes | Absolute `http` or `https` URL. |
| `description` | no | Second line on the card. |
| `monitor` | no | The monitor's name in Uptime Kuma, exactly as shown there. Gives the card a dot. |

In the Configuration tab's YAML view, for example:

```yaml
services:
  - group: Network
    name: Router
    url: https://192.168.1.1
    description: The gateway
    monitor: Router
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
| grey | no monitor of that name in Uptime Kuma (the tooltip says which). |
| dimmed | Uptime Kuma could not be read; the last verdict is shown and the footer says since when. |

Only cards with a `monitor` have a dot. The tooltip carries the response time and the check time. The browser probes nothing itself: a page served over HTTPS cannot reach plain-HTTP LAN services, and Uptime Kuma is the one verdict.

## Changing the cards

Settings, Apps, Start Page, Configuration, then Restart. The cards under Services are read at start; discovered cards follow the apps within five minutes.

## Troubleshooting

The footer and the app's log say what is missing.

| Footer or log | Cause | Fix |
|---|---|---|
| No Uptime Kuma found | No Uptime Kuma app installed and `uptime_kuma_url` empty | Install the Uptime Kuma app, or set `uptime_kuma_url`. |
| Uptime Kuma needs an API key | `uptime_kuma_api_key` empty | Make a key in Uptime Kuma, Settings, API Keys; set it and restart. |
| Unreachable, HTTP 401 | Wrong or revoked key | Make a new key in Uptime Kuma; an existing key cannot be read back. |
| Unreachable, connection refused | URL wrong for the app's network | Use the host's LAN address and Uptime Kuma's host port, not `localhost`. |
| One card grey, tooltip names the monitor | The name differs from Uptime Kuma's | Copy the monitor name exactly; it is case-sensitive. |
| No cards yet, apps could not be read | The Supervisor did not answer | The message names the answer; restart the app. |
| Card missing | It was dropped as invalid | Read the foot of the page or the app log. |

## Licence

MIT.
