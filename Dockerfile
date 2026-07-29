FROM python:3.11-slim

WORKDIR /app

# gosu drops privileges in the entrypoint once the runtime PUID/PGID fixup is
# done. It is preferred over `su`/`sudo` because it execs the target process
# directly instead of forking: the application keeps PID 1, so `docker stop`
# delivers SIGTERM to gunicorn itself and the shutdown is clean.
#
# The 1000:1000 default matches the first non-system account on virtually every
# desktop Linux and NAS, so the common case needs no PUID/PGID at all.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 metakavita \
    && useradd -u 1000 -g 1000 -M -d /app -s /usr/sbin/nologin metakavita

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
# Set the bit here rather than relying on the checked-out file mode: a clone made
# on Windows does not preserve the executable bit, and the build would otherwise
# fail only for contributors on that platform.
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 5010

# Liveness probe against the dedicated /healthz endpoint.
#
# This previously hit /login and accepted any status below 500, because there was
# no unauthenticated route that reliably answered 200 — every endpoint either
# redirects to the login page or is POST-only. That check was correct but blunt:
# "below 500" also passes for a 404, so a routing regression could have gone
# unnoticed. /healthz (misc.healthz) is whitelisted in `require_login`, so it
# answers 200 whether or not a password is set, and the check can demand exactly
# that.
#
# Uses the interpreter already in the image rather than adding curl or wget, which
# would mean another package in the final layer purely for this. `http.client`
# rather than urllib because it does not raise on 4xx/5xx, which keeps this a
# single expression — the status is inspected directly, and any genuine failure
# (connection refused, timeout) raises and exits non-zero anyway.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import http.client,sys; c=http.client.HTTPConnection('127.0.0.1',5010,timeout=4); c.request('GET','/healthz'); sys.exit(0 if c.getresponse().status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:5010", "app:app"]
