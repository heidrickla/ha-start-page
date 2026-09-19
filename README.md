# Home Assistant add-ons

| Add-on | What |
|---|---|
| [Start Page](start_page/) | Every home service on one page, with live status from Uptime Kuma. |

## Installing

Settings, Add-ons, Add-on store, the three dots, Repositories, add this
repository's URL. Or copy `start_page/` into the host's local add-ons
directory and reload the store.

## Developing

```bash
python -m pip install ruff pytest yamllint shellcheck-py
ruff check . && ruff format --check . && python -m pytest
python start_page/server.py --options options.json --www start_page/www --port 8090
```

`options.json` is the same shape the Supervisor writes to `/data/options.json`;
see `start_page/DOCS.md`.

## Licence

MIT. See `LICENSE`.
