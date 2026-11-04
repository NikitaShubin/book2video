#!/bin/sh
set -e

# Named volumes are created by Docker as root. Make the cache directories
# writable for the unprivileged app user once, then drop privileges.
mkdir -p /models/hf /cache
if [ "$(stat -c '%u' /models/hf)" != "1000" ]; then
    chown -R app:app /models/hf
fi
if [ "$(stat -c '%u' /cache)" != "1000" ]; then
    chown -R app:app /cache
fi

exec gosu app book2video "$@"
