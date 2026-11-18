"""Entrada de telemetría para los tres modos. Los tiempos se expresan en segundos."""

import csv
import gzip
import json
import math
import subprocess
import time


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def sample(payload, arrival):
    """Admite el objeto plano del lector TFG y el sobre de mensajes G3."""
    kind = payload.get("type")
    if kind not in (None, "gaze", "event"):
        return None
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None
    timestamp = number(payload.get("timestamp"))
    if timestamp is None:
        timestamp = number(data.get("timestamp"))
    record = {
        "timestamp": arrival if timestamp is None else timestamp,
        "clock": "reception" if timestamp is None else "source",
    }
    if kind == "event":
        label = data.get("label")
        if isinstance(label, str) and label.strip():
            return {**record, "label": label.strip()[:120]}
        return None

    gaze = data.get("gaze2d")
    x, y = (map(number, gaze[:2]) if isinstance(gaze, list) and len(gaze) >= 2
            else (None, None))

    def pupil(eye):
        value = data.get(eye)
        diameter = number(value.get("pupildiameter")) if isinstance(value, dict) else None
        return diameter if diameter is not None and diameter > 0 else None

    valid = x is not None and y is not None and 0 <= x <= 1 and 0 <= y <= 1
    if data.get("valid") is False:
        valid = False
    return {**record, "x": x, "y": y, "left": pupil("eyeleft"),
            "right": pupil("eyeright"), "valid": valid}


def json_objects(chunks):
    """Extrae objetos JSON del flujo de datos FFmpeg, incluso entre bloques."""
    frame = bytearray()
    depth = 0
    quoted = escaped = False
    for chunk in chunks:
        for byte in chunk:
            if depth == 0:
                if byte != ord("{"):
                    continue
                depth = 1
                frame.append(byte)
                continue
            frame.append(byte)
            if quoted:
                if escaped:
                    escaped = False
                elif byte == ord("\\"):
                    escaped = True
                elif byte == ord('"'):
                    quoted = False
            elif byte == ord('"'):
                quoted = True
            elif byte == ord("{"):
                depth += 1
            elif byte == ord("}"):
                depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(frame)
                    if isinstance(payload, dict):
                        yield payload
                except (ValueError, UnicodeError):
                    pass
                frame.clear()
            elif len(frame) > 65536:
                frame.clear()
                depth = 0
                quoted = escaped = False


def ffmpeg_command(url, stream):
    return ["ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp",
            "-timeout", "5000000", "-i", url, "-map", stream,
            "-c", "copy", "-f", "data", "-"]


def live_session(url, stream, stop, state):
    process = subprocess.Popen(ffmpeg_command(url, stream), stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    try:
        for payload in json_objects(iter(lambda: process.stdout.read1(4096), b"")):
            if stop.is_set():
                break
            record = sample(payload, time.time())
            if record:
                state.add(record)
    finally:
        process.kill()
        process.stdout.close()
        process.wait()


def live(url, stream, stop, state):
    while not stop.is_set():
        state.status("Buscando telemetría Tobii")
        try:
            live_session(url, stream, stop, state)
            state.status("Flujo RTSP cerrado · reintentando", reconnect=True)
        except FileNotFoundError:
            state.status("FFmpeg no está en PATH")
            return
        except OSError:
            state.status("Error de entrada RTSP · reintentando", reconnect=True)
        stop.wait(3)


def replay_records(path):
    def numeric(value):
        try:
            return number(float(value))
        except (TypeError, ValueError):
            return None

    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as file:
        if path.suffix.lower() == ".csv":
            rows = csv.DictReader(file)
            columns = {"timestamp", "gaze2d_x", "gaze2d_y", "pupil_left", "pupil_right"}
            if not columns.issubset(rows.fieldnames or []):
                raise ValueError("CSV incompatible")
            for row in rows:
                yield {
                    "timestamp": numeric(row["timestamp"]),
                    "gaze2d": [numeric(row["gaze2d_x"]), numeric(row["gaze2d_y"])],
                    "eyeleft": {"pupildiameter": numeric(row["pupil_left"])},
                    "eyeright": {"pupildiameter": numeric(row["pupil_right"])},
                }
        else:
            for line in file:
                if line.strip():
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        raise ValueError("Se esperaba un objeto JSON")
                    yield payload


def replay(path, scale, stop, state):
    previous = None
    deadline = time.monotonic()
    count = 0
    try:
        for payload in replay_records(path):
            record = sample(payload, 0)
            if record is None:
                continue
            if record["clock"] != "source":
                raise ValueError("Registro sin timestamp reproducible")
            record["timestamp"] /= scale
            timestamp = record["timestamp"]
            if previous is not None:
                deadline += max(0, timestamp - previous)
            if stop.wait(max(0, deadline - time.monotonic())):
                return
            state.add(record)
            previous = timestamp
            count += 1
    except (OSError, ValueError, EOFError, csv.Error):
        state.status("Error de lectura o formato del registro")
        return
    state.status("Reproducción finalizada" if count else "Registro sin telemetría compatible")


def demo(stop, state):
    start = time.monotonic()
    frame = 0
    while not stop.wait(max(0, start + frame / 50 - time.monotonic())):
        t = frame / 50
        phase = frame % 600
        frame += 1
        if 425 <= phase < 453:
            continue
        valid = not 210 <= phase < 222
        state.add({
            "timestamp": t, "clock": "synthetic", "valid": valid,
            "left": 3.6 + .22 * math.sin(t * 1.7) + .08 * math.sin(t * 4) if valid else None,
            "right": 3.95 + .24 * math.sin(t * 1.7 + .4) if valid else None,
            "x": .5 + .23 * math.sin(t * 1.3) if valid else None,
            "y": .51 + .16 * math.cos(t * .8 + .7) if valid else None,
        })
        if frame == 1 or phase == 300:
            state.add({"timestamp": t, "clock": "synthetic",
                       "label": "Inicio de sesión sintética" if frame == 1 else "Marcador de estímulo sintético"})
