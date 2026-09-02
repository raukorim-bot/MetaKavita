"""C96 — client SignalR Kavita : parse, debounce, WebSocket sur thread OS."""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

try:
    import eventlet
    _OSThreading = eventlet.patcher.original("threading")
    _OSSocket = eventlet.patcher.original("socket")
    _OSSsl = eventlet.patcher.original("ssl")
except Exception:
    import socket as _OSSocket
    import ssl as _OSSsl
    import threading as _OSThreading

SCAN_DEBOUNCE_S = 15
LIBRARY_IDLE_DEBOUNCE_S = 2
RECORD_SEPARATOR = "\x1e"
_HUB_PATH = "/hubs/messages"

_SCANNER_EVENTS = frozenset({
    "SeriesAdded",
    "ScanSeries",
    "ScanProgress",
    "ScanLibraryProgress",
    "NotificationProgress",
})
_PROGRESS_IGNORE = frozenset({
    "UserProgressUpdate",
    "UserUpdate",
    "ChapterRemoved",
    "SeriesRemoved",
})
_SCAN_HINTS = ("scan", "scanner", "scanfolder", "libraryscan")

_lock = _OSThreading.Lock()
_dirty = False
_last_activity = 0.0
_min_quiet = SCAN_DEBOUNCE_S
_status = "disconnected"
_last_error = ""


def reset_hub_logic_state():
    """Tests : remet dirty / timer / statut, sans toucher un socket."""
    global _dirty, _last_activity, _status, _last_error, _min_quiet
    with _lock:
        _dirty = False
        _last_activity = 0.0
        _min_quiet = SCAN_DEBOUNCE_S
        _status = "disconnected"
        _last_error = ""


def hub_public_status() -> dict:
    with _lock:
        err = _last_error or ""
    return {"status": _status, "last_error": err}


def parse_invocation(raw):
    """Une frame SignalR JSON (type 1) → (event_name, body) ou None."""
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, dict):
        return _invocation_from_obj(raw)
    text = str(raw).strip()
    if not text:
        return None
    for chunk in text.split(RECORD_SEPARATOR):
        piece = chunk.strip()
        if not piece:
            continue
        try:
            obj = json.loads(piece)
        except json.JSONDecodeError:
            continue
        parsed = _invocation_from_obj(obj)
        if parsed is not None:
            return parsed
    return None


def _invocation_from_obj(obj):
    if not isinstance(obj, dict):
        return None
    if obj.get("protocol") and "type" not in obj:
        return None
    msg_type = obj.get("type")
    if msg_type not in (None, 1):
        return None
    target = obj.get("target")
    args = obj.get("arguments")
    if not target and not args:
        return None
    if not isinstance(args, list):
        args = []
    if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], (dict, type(None))):
        return str(args[0]), args[1] or {}
    body = args[0] if args else {}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        body = {"value": body}
    name = str(target or "")
    if not name:
        return None
    return name, body


def is_scanner_event(name, body) -> bool:
    n = str(name or "").strip()
    if n in _PROGRESS_IGNORE:
        return False
    if n not in _SCANNER_EVENTS:
        return False
    if n != "NotificationProgress":
        return True
    blob = _body_blob(body)
    compact = blob.replace(" ", "")
    if "userprogress" in compact:
        return False
    return any(hint in blob for hint in _SCAN_HINTS)


def is_library_scan_idle(body) -> bool:
    """True seulement si le payload est clairement une bibliothèque et leftToProcess==0.

    Un Ended par série (ScanSeries) ne clôt pas le lot — debounce 15 s à la place.
    """
    payload = body if isinstance(body, dict) else {}
    nested = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    merged = {**nested, **payload}
    if not _is_library_payload(merged):
        return False
    left = merged.get("leftToProcess")
    if left is None:
        left = nested.get("leftToProcess")
    try:
        return int(left) == 0
    except (TypeError, ValueError):
        return False


def _is_library_payload(merged: dict) -> bool:
    if merged.get("seriesId") not in (None, "", 0, "0"):
        return False
    name = str(merged.get("name") or merged.get("title") or merged.get("event") or "")
    if "scanlibrary" in name.lower().replace(" ", ""):
        return True
    lib = merged.get("libraryId")
    if lib in (None, "", 0, "0"):
        return False
    return True


def _body_blob(body) -> str:
    if not isinstance(body, dict):
        return str(body or "").lower()
    parts = []
    for key in ("name", "title", "eventType", "event", "subtitle", "progressType"):
        val = body.get(key)
        if val not in (None, ""):
            parts.append(str(val))
    nested = body.get("body")
    if isinstance(nested, dict):
        parts.append(_body_blob(nested))
    return " ".join(parts).lower()


def note_scanner_activity(now=None, *, library_idle=False) -> None:
    global _dirty, _last_activity, _min_quiet
    ts = time.time() if now is None else float(now)
    with _lock:
        _dirty = True
        _last_activity = ts
        _min_quiet = LIBRARY_IDLE_DEBOUNCE_S if library_idle else SCAN_DEBOUNCE_S


def maybe_emit_scan_wake(now=None, *, min_quiet=None) -> bool:
    """Pousse `"scan"` une fois le silence écoulé. Un fire par rafale."""
    global _dirty
    ts = time.time() if now is None else float(now)
    with _lock:
        if not _dirty:
            return False
        quiet = float(min_quiet) if min_quiet is not None else _min_quiet
        if ts - _last_activity < quiet:
            return False
        _dirty = False
    _put_wake("scan")
    return True


def handle_invocation(name, body, now=None) -> bool:
    """True si un wake a été poussé (tests : frames fictives)."""
    n = str(name or "").strip()
    if n == "SeriesRemoved":
        try:
            b = body if isinstance(body, dict) else {}
            sid = b.get("seriesId") or b.get("id") or (b.get("value") if isinstance(b.get("value"), (int, str)) else None)
            if sid is not None:
                from db_manager import purge_single_series_from_all_caches
                purge_single_series_from_all_caches(int(sid))
                logging.info("[SignalR] SeriesRemoved reçu pour série #%s : caches invalidés.", sid)
        except Exception as e:
            logging.debug("SeriesRemoved cleanup failed: %s", e)

    if not is_scanner_event(name, body):
        return False
    ts = time.time() if now is None else float(now)
    note_scanner_activity(ts, library_idle=is_library_scan_idle(body))
    return maybe_emit_scan_wake(ts)


def _put_wake(reason: str) -> None:
    try:
        from services.background_tasks import auto_sync_wake_queue
        auto_sync_wake_queue.put_nowait(reason)
    except Exception as exc:
        logging.debug("auto_sync wake skipped: %s", exc)


def set_hub_status(status: str, last_error: str = "") -> None:
    """États publics. Jamais de JWT ici."""
    global _status, _last_error
    from secure_logging import redact_secrets

    allowed = {
        "disconnected", "connecting", "connected", "reconnecting", "error", "idle",
    }
    label = status if status in allowed else "error"
    err = redact_secrets(str(last_error or ""))
    if len(err) > 200:
        err = err[:200]
    with _lock:
        _status = label
        _last_error = err


def hub_http_url(kavita_url) -> str:
    raw = str(kavita_url or "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if parsed.scheme in ("ws", "wss"):
        scheme = "https" if parsed.scheme == "wss" else "http"
        parsed = parsed._replace(scheme=scheme)
    return urlunparse(parsed._replace(fragment="")).rstrip("/")


def hub_ws_url(kavita_url, connection_id=None, access_token=None) -> str:
    http = hub_http_url(kavita_url)
    parsed = urlparse(http)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = (parsed.path.rstrip("/") or "") + _HUB_PATH
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if connection_id:
        query["id"] = connection_id
    if access_token:
        query["access_token"] = access_token
    return urlunparse((scheme, parsed.netloc, path, "", urlencode(query), ""))


def _safe_netloc(url) -> str:
    return urlparse(str(url or "")).netloc or "?"


def plugin_jwt(config=None) -> str | None:
    """JWT plugin KavitaFetcher. Ne jamais logger la valeur."""
    from config_manager import load_config
    from kavita_api import KavitaAPI

    cfg = config if config is not None else load_config()
    api = KavitaAPI(cfg.get("KAVITA_URL"), cfg.get("KAVITA_API_KEY"))
    if not api.authenticate():
        return None
    token = getattr(api, "token", None)
    if not token:
        return None
    return str(token)


def negotiate(kavita_url, token, timeout=10) -> str | None:
    """POST negotiate ASP.NET. Rend connectionToken / connectionId."""
    base = hub_http_url(kavita_url)
    if not base or not token:
        return None
    url = base + _HUB_PATH + "/negotiate?negotiateVersion=1"
    code, raw = _http_request(
        "POST",
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        body=b"{}",
        timeout=timeout,
    )
    if code != 200:
        raise RuntimeError(f"negotiate HTTP {code} ({_safe_netloc(base)})")
    data = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
    return data.get("connectionToken") or data.get("connectionId")


def run_websocket_loop(stop_event) -> None:
    """Boucle reco : JWT → negotiate → WS. Sockets OS, pas eventlet."""
    backoff = 1.0
    while not getattr(stop_event, "is_set", lambda: False)():
        set_hub_status("connecting")
        try:
            _one_session(stop_event)
            backoff = 1.0
        except Exception as exc:
            from secure_logging import safe_exc_str

            set_hub_status("reconnecting", safe_exc_str(exc))
            logging.warning("[Kavita hub] %s", safe_exc_str(exc))
        wait = min(backoff, 60.0)
        backoff = min(backoff * 2.0, 60.0)
        if stop_event.wait(wait):
            break
    set_hub_status("disconnected")


_hub_thread = None
_hub_stop = None


def start_hub() -> None:
    """Idempotent. Thread OS hors greenthreads eventlet."""
    global _hub_thread, _hub_stop
    with _lock:
        if (
            _hub_thread is not None
            and _hub_thread.is_alive()
            and _hub_stop is not None
            and not _hub_stop.is_set()
        ):
            return
        _hub_stop = _OSThreading.Event()
        _hub_thread = _OSThreading.Thread(
            target=_hub_thread_main,
            name="kavita-hub",
            daemon=True,
        )
        _hub_thread.start()


def stop_hub() -> None:
    ev = _hub_stop
    if ev is not None:
        ev.set()
    set_hub_status("disconnected")


def _hub_thread_main() -> None:
    ev = _hub_stop
    if ev is None:
        return
    try:
        run_websocket_loop(ev)
    except Exception as exc:
        from secure_logging import safe_exc_str
        set_hub_status("error", safe_exc_str(exc))
        logging.warning("[Kavita hub] thread: %s", safe_exc_str(exc))


def _one_session(stop_event) -> None:
    from config_manager import load_config

    cfg = load_config()
    base = hub_http_url(cfg.get("KAVITA_URL"))
    if not base:
        raise RuntimeError("KAVITA_URL missing")
    token = plugin_jwt(cfg)
    if not token:
        raise RuntimeError(f"plugin JWT missing ({_safe_netloc(base)})")
    conn_id = negotiate(base, token)
    if not conn_id:
        raise RuntimeError(f"negotiate empty ({_safe_netloc(base)})")
    ws_url = hub_ws_url(base, connection_id=conn_id, access_token=token)
    sock = _ws_connect(ws_url, stop_event)
    try:
        set_hub_status("connected")
        payload = ('{"protocol":"json","version":1}' + RECORD_SEPARATOR).encode("utf-8")
        _ws_send(sock, payload, opcode=1)
        buf = b""
        while not stop_event.is_set():
            maybe_emit_scan_wake()
            try:
                sock.settimeout(1.0)
                chunk = sock.recv(4096)
            except _OSSocket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            frames, buf = _ws_feed(buf + chunk)
            for opcode, data in frames:
                if opcode == 8:
                    return
                if opcode == 9:
                    _ws_send(sock, data, opcode=10)
                    continue
                if opcode not in (1, 2):
                    continue
                text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data)
                for piece in text.split(RECORD_SEPARATOR):
                    piece = piece.strip()
                    if not piece:
                        continue
                    try:
                        obj = json.loads(piece)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == 6:
                        _ws_send(
                            sock,
                            (json.dumps({"type": 6}) + RECORD_SEPARATOR).encode("utf-8"),
                            opcode=1,
                        )
                        continue
                    parsed = parse_invocation(obj)
                    if parsed:
                        handle_invocation(parsed[0], parsed[1])
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _http_request(method, url, headers=None, body=b"", timeout=10):
    host, port, path, tls, netloc = _split_url(url)
    payload = body if isinstance(body, (bytes, bytearray)) else str(body or "").encode("utf-8")
    hdrs = {
        "Host": netloc,
        "Connection": "close",
        "Content-Length": str(len(payload)),
    }
    if headers:
        hdrs.update({str(k): str(v) for k, v in headers.items()})
    req = f"{method} {path} HTTP/1.1\r\n"
    for key, val in hdrs.items():
        req += f"{key}: {val}\r\n"
    blob = req.encode("ascii") + b"\r\n" + payload
    sock = _tcp_connect(host, port, tls, timeout)
    try:
        sock.sendall(blob)
        data = b""
        while True:
            try:
                chunk = sock.recv(65536)
            except _OSSocket.timeout:
                break
            if not chunk:
                break
            data += chunk
            if b"\r\n\r\n" in data and _http_body_complete(data):
                break
        header, _, rest = data.partition(b"\r\n\r\n")
        status = 0
        try:
            status = int(header.split(b"\r\n", 1)[0].split()[1])
        except (IndexError, ValueError):
            status = 0
        return status, rest
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _http_body_complete(data: bytes) -> bool:
    header, sep, rest = data.partition(b"\r\n\r\n")
    if not sep:
        return False
    lower = header.lower()
    if b"content-length:" in lower:
        try:
            for line in header.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1].strip())
                    return len(rest) >= length
        except (IndexError, ValueError):
            return True
    return True


def _split_url(url):
    parsed = urlparse(url)
    host = parsed.hostname or ""
    tls = parsed.scheme in ("https", "wss")
    port = parsed.port or (443 if tls else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    netloc = parsed.netloc or host
    return host, port, path, tls, netloc


def _tcp_connect(host, port, tls, timeout):
    raw = _OSSocket.create_connection((host, port), timeout=timeout)
    if not tls:
        return raw
    ctx = _OSSsl.create_default_context()
    return ctx.wrap_socket(raw, server_hostname=host)


def _ws_connect(ws_url, stop_event):
    host, port, path, tls, netloc = _split_url(ws_url)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {netloc}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock = _tcp_connect(host, port, tls, 15)
    try:
        sock.sendall(req.encode("ascii"))
        data = b""
        while b"\r\n\r\n" not in data:
            if stop_event.is_set():
                raise RuntimeError("hub stop")
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        header = data.split(b"\r\n\r\n", 1)[0].decode("ascii", "replace")
        if "101" not in header.split("\r\n", 1)[0]:
            raise RuntimeError(f"websocket upgrade {_safe_netloc(ws_url)}")
        return sock
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        raise


def _ws_send(sock, payload: bytes, opcode=1) -> None:
    mask = os.urandom(4)
    header = bytearray()
    header.append(0x80 | (opcode & 0x0F))
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    header.extend(mask)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(header + masked)


def _ws_feed(buf: bytes):
    frames = []
    while True:
        if len(buf) < 2:
            return frames, buf
        b1, b2 = buf[0], buf[1]
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        ln = b2 & 0x7F
        idx = 2
        if ln == 126:
            if len(buf) < 4:
                return frames, buf
            ln = struct.unpack("!H", buf[2:4])[0]
            idx = 4
        elif ln == 127:
            if len(buf) < 10:
                return frames, buf
            ln = struct.unpack("!Q", buf[2:10])[0]
            idx = 10
        if masked:
            if len(buf) < idx + 4:
                return frames, buf
            mask = buf[idx:idx + 4]
            idx += 4
        else:
            mask = None
        if len(buf) < idx + ln:
            return frames, buf
        data = buf[idx:idx + ln]
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        buf = buf[idx + ln:]
        frames.append((opcode, data))
    return frames, buf

