# Start Page for Home Assistant

A Home Assistant app that puts every home service on one page: grouped link cards with a filter and a dark or light theme, in the Home Assistant sidebar and on a port of its own. Home Assistant and each running app with a web interface get a card without typing; Uptime Kuma, when installed, colours each card's status dot.

## Install

[![Open your Home Assistant instance and show the add app repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fheidrickla%2Fha-start-page)

[![Open your Home Assistant instance and show the Start Page app.](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?addon=8e10ddb7_start_page&repository_url=https%3A%2F%2Fgithub.com%2Fheidrickla%2Fha-start-page)

1. Select the first button to add this repository, then the second to open Start Page.
2. Select Install, then Start.
3. Turn on Show in sidebar, then open Start.
4. For status dots, make an API key in Uptime Kuma (Settings, API Keys) and paste it into Uptime Kuma API key on the Configuration tab, then restart.

Cards for Home Assistant and its apps appear on their own. Cards of your own go under Services on the Configuration tab.

## Options

| Option | Default | Effect |
|---|---|---|
| Title | Home | Brand text and browser title. |
| Tagline | start here | The small line under the title. |
| Introduction | a short paragraph | The paragraph above the cards. Empty hides it. |
| Discover cards | on | A card for Home Assistant and one for each running app with a web interface. A card under Services with the same name replaces the discovered one. |
| Uptime Kuma URL | empty | Empty finds the Uptime Kuma app on this Home Assistant. Set it for an Uptime Kuma elsewhere. |
| Uptime Kuma API key | empty | Needed for status dots. |
| Verify Uptime Kuma's certificate | on | On an `https` URL the key is sent only to a certificate that verifies. |
| Uptime Kuma CA file | empty | A CA certificate under `/ssl` that signed Uptime Kuma's certificate. |
| Status interval | 30 | Seconds between status reads, 10 to 600. |
| Services | none | Cards of your own: group, name, URL, and optionally a description and the Uptime Kuma monitor name. |

The Documentation tab of the app has the details: [start_page/DOCS.md](start_page/DOCS.md).

## Developing

```bash
python -m pip install ruff pytest yamllint shellcheck-py
ruff check . && ruff format --check . && python -m pytest
python start_page/server.py --options options.json --www start_page/www --port 8090
```

`options.json` is the same shape the Supervisor writes to `/data/options.json`. Outside the Supervisor there is no `SUPERVISOR_TOKEN`, so only the cards under `services` show.

## Licence

MIT. See `LICENSE`.
