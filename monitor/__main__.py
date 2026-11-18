"""Servidor local y estado compartido del monitor."""

import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Event, Lock, Thread
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from .sources import demo, live, replay

WEB = Path(__file__).with_name("web")
GAP_SECONDS = 0.150
SILENCE_SECONDS = 2


class Monitor:
    def __init__(self, mode):
        self.mode = mode
        self.session = uuid4().hex
        self.lock = Lock()
        self.records = deque(maxlen=65000)
        self.seq = 0
        self.message = "Esperando muestras"
        self.last = None
        self.origin = None
        self.last_arrival = None
        self.reconnect = False

    def status(self, message, reconnect=False):
        with self.lock:
            self.message = message
            self.reconnect |= reconnect

    def append(self, record):
        self.seq += 1
        self.records.append({**record, "seq": self.seq})

    def add(self, record):
        with self.lock:
            arrival = time.monotonic()
            last = self.last
            if last is None:
                if self.origin is None:
                    self.origin = (record["clock"], record["timestamp"])
                clock, timestamp = self.origin
                t = max(0, record["timestamp"] - timestamp) if clock == record["clock"] else 0
                reason = None
            else:
                delay = record["timestamp"] - last["timestamp"]
                reason = None
                if (self.reconnect or last["clock"] != record["clock"] or delay < 0
                        or (self.mode == "LIVE" and arrival - self.last_arrival > SILENCE_SECONDS
                            and delay <= GAP_SECONDS)):
                    delay = arrival - self.last_arrival
                    reason = "Cambio de segmento temporal"
                elif delay > GAP_SECONDS:
                    reason = "Intervalo sin muestras"
                t = last["t"] + delay
            if "label" in record:
                if last is not None and (record["clock"] != last["clock"] or self.reconnect):
                    t = last["t"]
                self.append({**record, "t": t})
                return
            self.reconnect = False
            self.last_arrival = arrival
            self.last = {**record, "t": t, "gap": reason,
                         "gapStart": last["t"] if reason else None}
            self.append(self.last)
            self.message = {"LIVE": "Tobii · recibiendo telemetría",
                            "REPLAY": "Reproduciendo registro",
                            "DEMO": "Simulación activa"}[self.mode]
            while self.records and self.records[0]["t"] < t - 65:
                self.records.popleft()

    def marker(self, label):
        with self.lock:
            anchor = self.last or {"t": 0}
            self.append({"label": label, "t": anchor["t"],
                         "timestamp": time.time(), "clock": "operator"})

    def snapshot(self, after):
        with self.lock:
            cutoff = self.last["t"] - 65 if self.last else 0
            message = self.message
            silent = (self.mode == "LIVE" and self.last is not None
                      and time.monotonic() - self.last_arrival > SILENCE_SECONDS)
            receiving = self.mode == "LIVE" and not silent and message.startswith("Tobii ·")
            if silent and message.startswith("Tobii ·"):
                message = "Tobii · sin muestras recientes"
            # El cursor es contiguo en la cola, incluso después de su poda.
            count = min(len(self.records), max(0, self.seq - after))
            tail = list(self.records)[-count:] if count else []
            return {"mode": self.mode, "status": message, "receiving": receiving,
                    "session": self.session, "cursor": self.seq, "records": [r for r in tail if r["t"] >= cutoff]}


def handler_for(state):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, body, media, status=200):
            self.send_response(status)
            self.send_header("Content-Type", media)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == "/api/state":
                params = parse_qs(url.query)
                value = params.get("after", ["0"])[0]
                after = int(value) if value.isascii() and value.isdigit() and len(value) < 16 else 0
                if params.get("session") != [state.session]:
                    after = 0
                self.respond(json.dumps(state.snapshot(after), allow_nan=False).encode(),
                             "application/json")
                return
            assets = {"/": ("index.html", "text/html"), "/style.css": ("style.css", "text/css"),
                      "/dashboard.js": ("dashboard.js", "text/javascript")}
            if url.path in assets:
                filename, media = assets[url.path]
                self.respond((WEB / filename).read_bytes(), media + "; charset=utf-8")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/api/marker":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024 or self.headers.get_content_type() != "application/json":
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
                label = payload.get("label") if isinstance(payload, dict) else None
                if not isinstance(label, str) or not 0 < len(label.strip()) <= 120:
                    raise ValueError
            except (ValueError, UnicodeError):
                self.send_error(400)
                return
            state.marker(label.strip())
            self.respond(b"{}", "application/json", 201)

        def log_message(self, *_args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description="ADICVIDEO – Real-Time Eye Tracking Monitor")
    parser.add_argument("--mode", choices=("demo", "replay", "live"), default="demo")
    parser.add_argument("--rtsp", default="rtsp://192.168.75.51:8554/live/all")
    parser.add_argument("--stream", default="0:3")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--time-unit", choices=("s", "ms", "us"), default="s")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    if args.mode == "replay" and (args.file is None or not args.file.is_file()):
        parser.error("REPLAY requiere --file con un archivo local existente")
    state = Monitor(args.mode.upper())
    stop = Event()
    scale = {"s": 1, "ms": 1000, "us": 1000000}[args.time_unit]
    sources = {"live": (live, (args.rtsp, args.stream)), "demo": (demo, ()),
               "replay": (replay, (args.file, scale))}
    source, options = sources[args.mode]
    with ThreadingHTTPServer((args.host, args.port), handler_for(state)) as server:
        worker = Thread(target=source, args=(*options, stop, state), daemon=True)
        worker.start()
        print(f"{state.mode} · http://{args.host}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            worker.join(timeout=6)


if __name__ == "__main__":
    main()
