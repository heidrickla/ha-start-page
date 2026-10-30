#!/command/with-contenv sh
# shellcheck shell=sh
# with-contenv hands over the container's environment, SUPERVISOR_TOKEN included, which S6 overlay
# keeps from CMD. Options are read by the server from /data/options.json; nothing rides argv.
set -eu

echo "[start-page] serving on :8090"
exec python3 /opt/start_page/server.py --options /data/options.json --www /opt/start_page/www --port 8090
