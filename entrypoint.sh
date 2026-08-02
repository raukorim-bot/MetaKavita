#!/bin/sh
#
# MetaKavita container entrypoint — linuxserver.io-style PUID/PGID handling.
#
# The image ships a dedicated unprivileged user (metakavita, 1000:1000) rather
# than running the application as root. That alone would be enough for security,
# but it is not enough for a self-hoster: the ./data bind mount is a directory on
# THEIR filesystem, owned by THEIR uid, and a container user with a fixed uid of
# 1000 will simply be unable to write to it whenever their account is 1001, or
# 1026 on a Synology, or anything else.
#
# So the uid/gid are decided at RUNTIME from PUID/PGID rather than baked in at
# build time. That is the whole reason this script exists: a Dockerfile USER
# directive is static, and a static uid is what breaks people's permissions.
#
# The script runs as root and does exactly three things before giving that up:
#   1. move the metakavita user/group to the requested uid/gid,
#   2. take ownership of the paths the application writes to,
#   3. drop to the unprivileged user with gosu and exec the real command.
#
# `exec` matters: gunicorn replaces this shell as PID 1, so it receives SIGTERM
# from `docker stop` directly and shuts down cleanly instead of being killed
# after the timeout.
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

APP_USER=metakavita
APP_GROUP=metakavita
DATA_DIR=/app/data

# If the container was started with `--user` (or `user:` in compose), we are
# already unprivileged and none of the fixup below is possible — usermod and
# chown both need root. That is a legitimate way to run this image for someone
# who manages ownership themselves, so honour it instead of failing: skip
# straight to the command.
if [ "$(id -u)" != "0" ]; then
    echo "[entrypoint] Running as uid $(id -u) (not root) — skipping PUID/PGID setup."
    # The application creates data/ relative to its working directory, so it only
    # needs the directory to be writable. Warn rather than exit: the user chose
    # this mode and may well have set the ownership correctly on the host.
    if [ ! -w "$DATA_DIR" ] && [ -e "$DATA_DIR" ]; then
        echo "[entrypoint] WARNING: $DATA_DIR is not writable by uid $(id -u)."
    fi
    exec "$@"
fi

# Reassign the group first, then the user. `-o` permits a non-unique id, which is
# needed because the requested uid may already belong to another account inside
# the image (uid 1000 is 'ubuntu' or similar on some bases).
if [ "$PGID" != "$(id -g $APP_USER)" ]; then
    groupmod -o -g "$PGID" "$APP_GROUP"
fi
if [ "$PUID" != "$(id -u $APP_USER)" ]; then
    usermod -o -u "$PUID" "$APP_USER"
fi

echo "[entrypoint] Starting MetaKavita as ${APP_USER} (uid $(id -u $APP_USER), gid $(id -g $APP_USER))."

# Create the data directory before dropping privileges. The application does
# `os.makedirs("data")` itself, but by then it is unprivileged and /app is
# root-owned, so it would fail on a first run with no bind mount.
mkdir -p "$DATA_DIR" "$DATA_DIR/scrapers"

# Take ownership of everything the application writes: config.json, cache.db,
# metakavita.log, and any sideloaded scraper under data/scrapers/.
#
# This is also the upgrade path. Anyone running a previous version was running it
# as root, so their existing bind-mounted data/ is full of root-owned files that
# the new unprivileged process could not otherwise open. Doing it on every start
# rather than only when the directory looks wrong keeps that repair automatic and
# idempotent — and cheap, since data/ holds a handful of small files.
chown -R "$PUID:$PGID" "$DATA_DIR"

exec gosu "$APP_USER" "$@"
