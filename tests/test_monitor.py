import gzip
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import MagicMock, patch
from urllib.request import Request, urlopen

from monitor.__main__ import Monitor, ThreadingHTTPServer, handler_for
from monitor.sources import ffmpeg_command, json_objects, live_session, replay, sample


class SamplesTest(unittest.TestCase):
    def test_envelope_retains_device_time_and_independent_pupils(self):
        record = sample({"type": "gaze", "timestamp": 0, "data": {
            "gaze2d": [0.2, 0.8], "eyeleft": {"pupildiameter": 3.8},
            "eyeright": {"pupildiameter": 4.2}}}, arrival=100)
        self.assertEqual(record, {"timestamp": 0, "clock": "source", "x": 0.2,
                                 "y": 0.8, "left": 3.8, "right": 4.2, "valid": True})

    def test_invalid_gaze_is_not_a_blink_and_preserves_available_pupil(self):
        record = sample({"gaze2d": [-1, float("nan")],
                         "eyeright": {"pupildiameter": 3.1}}, arrival=100)
        self.assertFalse(record["valid"])
        self.assertNotIn("blink", record)
        self.assertEqual((record["right"], record["left"]), (3.1, None))
        self.assertEqual((record["timestamp"], record["clock"]), (100, "reception"))
        self.assertIsNone(sample({"type": "sync"}, 100))

    def test_ffmpeg_contract_and_byte_stream(self):
        url = "rtsp://127.0.0.1:8554/live/all"
        self.assertEqual(ffmpeg_command(url, "0:3")[3:],
                         ["error", "-rtsp_transport", "tcp", "-timeout", "5000000",
                          "-i", url, "-map", "0:3", "-c", "copy", "-f", "data", "-"])
        packet = b'noise{"broken":}{"type":"gaze","gaze2d":[0.1,0.2],"timestamp":4}'
        self.assertEqual(len(list(json_objects([packet[:34], packet[34:]]))), 1)
        process = MagicMock(stdout=io.BytesIO(packet))
        state = Monitor("LIVE")
        with patch("monitor.sources.subprocess.Popen", return_value=process):
            live_session(url, "0:3", Event(), state)
        self.assertTrue(state.snapshot(0)["receiving"])
        self.assertEqual(state.snapshot(0)["records"][0]["timestamp"], 4)
        process.wait.assert_called_once()

    def test_json_framing_handles_quoted_braces_and_utf8(self):
        packet = json.dumps({"label": 'señal {"a"}'}, ensure_ascii=False).encode()
        self.assertEqual(list(json_objects(bytes([b]) for b in packet)),
                         [{"label": 'señal {"a"}'}])


class StateTest(unittest.TestCase):
    def test_gap_invalid_marker_and_incremental_poll(self):
        state = Monitor("LIVE")
        for t, gaze in [(10, [.3, .2]), (10.02, None), (10.4, [.3, .2])]:
            state.add(sample({"timestamp": t, "gaze2d": gaze}, 100))
        state.marker("Inicio")
        snapshot = state.snapshot(1)
        bad, gap, event = snapshot["records"]
        self.assertFalse(bad["valid"])
        self.assertIsNone(bad["gap"])
        self.assertTrue(gap["valid"])
        self.assertEqual(gap["gap"], "Intervalo sin muestras")
        self.assertAlmostEqual(gap["t"], .4)
        self.assertEqual(event["clock"], "operator")
        self.assertEqual(event["t"], gap["t"])
        self.assertEqual(state.snapshot(snapshot["cursor"])["records"], [])

    def test_reset_clock_and_no_artificial_samples_during_silence(self):
        state = Monitor("LIVE")
        with patch("monitor.__main__.time.monotonic", return_value=1):
            state.add(sample({"timestamp": 10, "gaze2d": [.3, .2]}, 0))
        with patch("monitor.__main__.time.monotonic", return_value=4):
            snap = state.snapshot(0)
            self.assertFalse(snap["receiving"])
            self.assertEqual(len(snap["records"]), 1)
            state.add(sample({"timestamp": 0, "gaze2d": [.3, .2]}, 0))
        last = state.snapshot(1)["records"][0]
        self.assertEqual(last["gap"], "Cambio de segmento temporal")
        self.assertEqual(last["t"], 3)

    def test_replay_csv_uses_units_and_retains_missing_rows(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.csv"
            path.write_text("timestamp,gaze2d_x,gaze2d_y,pupil_left,pupil_right\n"
                            "900,0.2,0.3,3.4,3.6\n920,,,,\n")
            state = Monitor("REPLAY")
            replay(path, 1000, Event(), state)
        snap = state.snapshot(0)
        self.assertEqual(snap["status"], "Reproducción finalizada")
        first, second = snap["records"]
        self.assertEqual(first["timestamp"], .9)
        self.assertAlmostEqual(second["t"], .02)
        self.assertFalse(second["valid"])

    def test_replay_gzip_event_and_missing_timestamp(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gz"
            with gzip.open(path, "wt") as file:
                file.write('{"timestamp":1,"type":"event","data":{"label":"Inicio"}}\n')
                file.write('{"gaze2d":[0,0]}\n')
            state = Monitor("REPLAY")
            replay(path, 1, Event(), state)
        snap = state.snapshot(0)
        self.assertEqual(snap["records"][0]["label"], "Inicio")
        self.assertIn("Error", snap["status"])

    def test_http_serves_dashboard_and_marks_event(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), handler_for(Monitor("DEMO"))) as server:
            worker = Thread(target=server.serve_forever)
            worker.start()
            url = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(url, timeout=2) as response:
                    self.assertIn(b"Real-Time Eye Tracking Monitor", response.read())
                request = Request(url + "/api/marker", data=b'{"label":"Inicio"}',
                                  headers={"Content-Type": "application/json"})
                with urlopen(request, timeout=2) as response:
                    self.assertEqual(response.status, 201)
                with urlopen(url + "/api/state", timeout=2) as response:
                    snap = json.load(response)
                self.assertEqual(snap["mode"], "DEMO")
                self.assertEqual(snap["records"][0]["label"], "Inicio")
            finally:
                server.shutdown()
                worker.join()
