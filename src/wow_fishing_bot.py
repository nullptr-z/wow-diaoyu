#!/usr/bin/env python3
import argparse
import copy
import json
import os
import queue
import threading
import time
import wave
from dataclasses import dataclass

import cv2
import numpy as np
import sounddevice as sd
from mss import mss
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController, Listener as MouseListener

DEFAULT_CONFIG = {
    "cast_key": "1",
    "cast_delay_sec": 1.5,
    "audio": {
        "sample_rate": 44100,
        "fft_size": 2048,
        "freq_target_hz": 1200,
        "freq_band_hz": 300,
        "ratio_threshold": 0.35,
        "consecutive_hits": 2,
        "wasapi_loopback": False,
        "device": None,
    },
    "vision": {
        "template_path": "assets/bobber_template.png",
        "search_region": {
            "left": 200,
            "top": 200,
            "width": 800,
            "height": 600,
        },
        "match_threshold": 0.75,
    },
    "click": {
        "move_delay_sec": 0.05,
        "post_click_delay_sec": 0.2,
    },
    "loop": {
        "idle_sleep_sec": 0.05,
        "max_wait_sec": 25,
    },
}


def merge_dicts(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_dicts(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path):
    config = copy.deepcopy(DEFAULT_CONFIG)
    with open(path, "r", encoding="utf-8") as fh:
        user_config = json.load(fh)
    return merge_dicts(config, user_config)


SPECIAL_KEYS = {
    "space": Key.space,
    "enter": Key.enter,
    "esc": Key.esc,
    "tab": Key.tab,
}


def parse_key(key_name):
    key_name = key_name.strip().lower()
    return SPECIAL_KEYS.get(key_name, key_name)


def _find_pyaudio_loopback():
    """Find a WASAPI loopback device using pyaudiowpatch."""
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        return None, None, None
    p = pyaudio.PyAudio()
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError:
        p.terminate()
        return None, None, None
    default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if dev.get("isLoopbackDevice") and default_out["name"] in dev["name"]:
            print(f"[audio] found WASAPI loopback: {dev['name']}")
            return p, dev, pyaudio
    p.terminate()
    return None, None, None


@dataclass
class AudioConfig:
    sample_rate: int
    fft_size: int
    freq_target_hz: float
    freq_band_hz: float
    ratio_threshold: float
    consecutive_hits: int
    wasapi_loopback: bool
    device: int | None


class AudioDetector:
    def __init__(self, config: AudioConfig):
        self.config = config
        self.queue = queue.Queue(maxsize=50)
        self.stream = None
        self.window = np.hanning(config.fft_size)
        self.freqs = np.fft.rfftfreq(config.fft_size, d=1.0 / config.sample_rate)
        low = config.freq_target_hz - config.freq_band_hz / 2
        high = config.freq_target_hz + config.freq_band_hz / 2
        self.band_mask = (self.freqs >= low) & (self.freqs <= high)
        self.hit_count = 0

    def start(self):
        if self.stream is not None:
            return
        if self.config.wasapi_loopback:
            self._start_loopback()
        else:
            self.stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                blocksize=self.config.fft_size,
                channels=1,
                callback=self._callback,
                device=self.config.device,
            )
            self.stream.start()

    def _start_loopback(self):
        p, dev, pyaudio = _find_pyaudio_loopback()
        if p is None:
            raise RuntimeError(
                "WASAPI loopback not available. Install pyaudiowpatch:\n"
                "  pip install pyaudiowpatch"
            )
        self._pyaudio = p
        self._loopback_running = True
        self.stream = p.open(
            format=pyaudio.paFloat32,
            channels=dev["maxInputChannels"],
            rate=int(dev["defaultSampleRate"]),
            input=True,
            input_device_index=dev["index"],
            frames_per_buffer=self.config.fft_size,
        )
        self._loopback_channels = dev["maxInputChannels"]
        self._loopback_rate = int(dev["defaultSampleRate"])
        if self._loopback_rate != self.config.sample_rate:
            self._loopback_read_size = int(
                np.ceil(self.config.fft_size * self._loopback_rate / self.config.sample_rate)
            )
        else:
            self._loopback_read_size = self.config.fft_size
        self._loopback_thread = threading.Thread(target=self._loopback_reader, daemon=True)
        self._loopback_thread.start()

    def _loopback_reader(self):
        while self._loopback_running:
            try:
                raw = self.stream.read(self._loopback_read_size, exception_on_overflow=False)
                data = np.frombuffer(raw, dtype=np.float32)
                if self._loopback_channels > 1:
                    data = data.reshape(-1, self._loopback_channels)[:, 0]
                if self._loopback_rate != self.config.sample_rate:
                    indices = np.linspace(0, len(data) - 1, self.config.fft_size).astype(int)
                    data = data[indices]
                self._callback(data.reshape(-1, 1), None, None, None)
            except Exception:
                if self._loopback_running:
                    continue
                break

    def stop(self):
        if self.stream is None:
            return
        if hasattr(self, '_loopback_running'):
            self._loopback_running = False
            self._loopback_thread.join(timeout=2)
            self.stream.stop_stream()
            self.stream.close()
            self._pyaudio.terminate()
        else:
            self.stream.stop()
            self.stream.close()
        self.stream = None

    def flush(self):
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.hit_count = 0

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}")
        try:
            self.queue.put_nowait(indata.copy())
        except queue.Full:
            pass

    def _score_chunk(self, chunk):
        data = chunk[:, 0]
        if data.shape[0] != self.config.fft_size:
            return 0.0
        spectrum = np.fft.rfft(data * self.window)
        magnitude = np.abs(spectrum)
        band_energy = np.mean(magnitude[self.band_mask])
        total_energy = np.mean(magnitude) + 1e-9
        return band_energy / total_energy

    def poll_hook(self, timeout_sec):
        try:
            chunk = self.queue.get(timeout=timeout_sec)
        except queue.Empty:
            return False
        score = self._score_chunk(chunk)
        if score >= self.config.ratio_threshold:
            self.hit_count += 1
        else:
            self.hit_count = 0
        return self.hit_count >= self.config.consecutive_hits


def _record_loopback(config: AudioConfig, seconds: float):
    p, dev, pyaudio = _find_pyaudio_loopback()
    if p is None:
        raise RuntimeError(
            "WASAPI loopback not available. Install pyaudiowpatch:\n"
            "  pip install pyaudiowpatch"
        )
    channels = dev["maxInputChannels"]
    rate = int(dev["defaultSampleRate"])
    stream = p.open(
        format=pyaudio.paFloat32,
        channels=channels,
        rate=rate,
        input=True,
        input_device_index=dev["index"],
        frames_per_buffer=config.fft_size,
    )
    total_frames = int(seconds * rate)
    chunks = []
    read = 0
    while read < total_frames:
        n = min(config.fft_size, total_frames - read)
        raw = stream.read(n, exception_on_overflow=False)
        chunks.append(np.frombuffer(raw, dtype=np.float32))
        read += n
    stream.stop_stream()
    stream.close()
    p.terminate()
    data = np.concatenate(chunks)
    if channels > 1:
        data = data.reshape(-1, channels)[:, 0]
    if rate != config.sample_rate:
        new_len = int(len(data) * config.sample_rate / rate)
        indices = np.linspace(0, len(data) - 1, new_len).astype(int)
        data = data[indices]
    return data.reshape(-1, 1)


def record_audio(config: AudioConfig, seconds: float, output_path: str):
    if seconds <= 0:
        raise ValueError("record seconds must be > 0")
    print(f"[record] start {seconds:.1f}s at {config.sample_rate} Hz")
    if config.wasapi_loopback:
        data = _record_loopback(config, seconds)
    else:
        frames = max(1, int(seconds * config.sample_rate))
        data = sd.rec(
            frames,
            samplerate=config.sample_rate,
            channels=1,
            dtype="float32",
            device=config.device,
            blocking=True,
        )
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767).astype(np.int16)
    folder = os.path.dirname(output_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(config.sample_rate)
        wf.writeframes(pcm.tobytes())
    print(f"[record] saved {output_path}")


def wait_for_click(timeout_sec):
    event = threading.Event()
    result = {}

    def on_click(x, y, button, pressed):
        if pressed:
            result["pos"] = (int(x), int(y))
            event.set()
            return False
        return None

    listener = MouseListener(on_click=on_click)
    listener.start()
    event.wait(timeout_sec)
    listener.stop()
    listener.join()
    if "pos" not in result:
        raise TimeoutError("capture timeout")
    return result["pos"]


def capture_region(timeout_sec: float):
    """Wait for two clicks (top-left, bottom-right) and return the region."""
    if timeout_sec <= 0:
        raise ValueError("capture timeout must be > 0")
    print(f"[region] click TOP-LEFT corner within {timeout_sec:.1f}s")
    x1, y1 = wait_for_click(timeout_sec)
    print(f"[region] got top-left: ({x1}, {y1})")
    print(f"[region] now click BOTTOM-RIGHT corner within {timeout_sec:.1f}s")
    x2, y2 = wait_for_click(timeout_sec)
    print(f"[region] got bottom-right: ({x2}, {y2})")
    left = min(x1, x2)
    top = min(y1, y2)
    width = abs(x2 - x1)
    height = abs(y2 - y1)
    if width <= 0 or height <= 0:
        raise ValueError("region has zero area — two clicks are at the same position")
    print(f"[region] result: left={left}, top={top}, width={width}, height={height}")
    return {"left": left, "top": top, "width": width, "height": height}


def capture_bobber(size: int, output_path: str, timeout_sec: float):
    if size <= 0:
        raise ValueError("capture size must be > 0")
    if timeout_sec <= 0:
        raise ValueError("capture timeout must be > 0")
    print(f"[capture] click the bobber within {timeout_sec:.1f}s")
    x, y = wait_for_click(timeout_sec)
    with mss() as sct:
        monitor = sct.monitors[0]
        left = int(x - size // 2)
        top = int(y - size // 2)
        max_left = monitor["left"]
        max_top = monitor["top"]
        max_right = max_left + monitor["width"]
        max_bottom = max_top + monitor["height"]
        left = max(max_left, min(left, max_right - 1))
        top = max(max_top, min(top, max_bottom - 1))
        width = min(size, max_right - left)
        height = min(size, max_bottom - top)
        if width <= 0 or height <= 0:
            raise ValueError("capture region out of bounds")
        region = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        }
        frame = np.array(sct.grab(region))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
    folder = os.path.dirname(output_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    cv2.imwrite(output_path, gray)
    print(f"[capture] saved {output_path} ({width}x{height})")


@dataclass
class VisionConfig:
    template_path: str
    search_left: int
    search_top: int
    search_width: int
    search_height: int
    match_threshold: float


class VisionLocator:
    def __init__(self, config: VisionConfig):
        self.config = config
        self.template = cv2.imread(config.template_path, cv2.IMREAD_GRAYSCALE)
        if self.template is None:
            raise FileNotFoundError(f"template not found: {config.template_path}")
        self.template_h, self.template_w = self.template.shape
        self.sct = mss()

    def find(self):
        region = {
            "left": self.config.search_left,
            "top": self.config.search_top,
            "width": self.config.search_width,
            "height": self.config.search_height,
        }
        print(f"[vision] searching region: left={region['left']}, top={region['top']}, "
              f"width={region['width']}, height={region['height']}")
        print(f"[vision] template size: {self.template_w}x{self.template_h}")
        frame = np.array(self.sct.grab(region))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        result = cv2.matchTemplate(gray, self.template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        print(f"[vision] best match: score={max_val:.4f}, pos={max_loc}, threshold={self.config.match_threshold}")
        if max_val < self.config.match_threshold:
            print(f"[vision] REJECTED: score {max_val:.4f} < threshold {self.config.match_threshold}")
            return None
        x = region["left"] + max_loc[0] + self.template_w // 2
        y = region["top"] + max_loc[1] + self.template_h // 2
        print(f"[vision] MATCHED: clicking at ({x}, {y})")
        return (x, y, max_val)


class InputController:
    def __init__(self, cast_key, move_delay_sec, post_click_delay_sec):
        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        self.cast_key = parse_key(cast_key)
        self.move_delay_sec = move_delay_sec
        self.post_click_delay_sec = post_click_delay_sec

    def cast(self):
        self.keyboard.press(self.cast_key)
        self.keyboard.release(self.cast_key)

    def click(self, x, y):
        self.mouse.position = (x, y)
        if self.move_delay_sec:
            time.sleep(self.move_delay_sec)
        self.mouse.click(Button.left, 1)
        if self.post_click_delay_sec:
            time.sleep(self.post_click_delay_sec)


class FishingBot:
    def __init__(self, config):
        audio_cfg = AudioConfig(**config["audio"])
        vision_cfg = VisionConfig(
            template_path=config["vision"]["template_path"],
            search_left=config["vision"]["search_region"]["left"],
            search_top=config["vision"]["search_region"]["top"],
            search_width=config["vision"]["search_region"]["width"],
            search_height=config["vision"]["search_region"]["height"],
            match_threshold=config["vision"]["match_threshold"],
        )
        self.audio = AudioDetector(audio_cfg)
        self.vision = VisionLocator(vision_cfg)
        self.input = InputController(
            config["cast_key"],
            config["click"]["move_delay_sec"],
            config["click"]["post_click_delay_sec"],
        )
        self.cast_delay_sec = config["cast_delay_sec"]
        self.max_wait_sec = config["loop"]["max_wait_sec"]
        self.idle_sleep_sec = config["loop"]["idle_sleep_sec"]

    def run(self, once=False, countdown=5):
        print(f"[bot] starting in {countdown} seconds, switch to game window now!")
        for i in range(countdown, 0, -1):
            print(f"  {i}...")
            time.sleep(1)
        self.audio.start()
        print("[bot] started, press Ctrl+C to stop.")
        try:
            while True:
                print("[bot] cast")
                self.input.cast()
                time.sleep(self.cast_delay_sec)
                self.audio.flush()

                deadline = time.monotonic() + self.max_wait_sec
                hooked = False
                while time.monotonic() < deadline:
                    if self.audio.poll_hook(timeout_sec=0.25):
                        hooked = True
                        break
                    time.sleep(self.idle_sleep_sec)

                if not hooked:
                    print("[bot] no hook detected, recast")
                    if once:
                        return
                    continue

                print("[bot] hook detected! looking for bobber...")
                match = self.vision.find()
                if match is None:
                    print("[bot] hook detected, but no bobber match — skipping click, recast")
                    if once:
                        return
                    continue

                x, y, score = match
                print(f"[bot] click at ({x}, {y}), score={score:.3f}")
                self.input.click(x, y)
                print("[bot] click done, waiting before next cast")
                if once:
                    return
        except KeyboardInterrupt:
            print("\n[bot] stopped")
        finally:
            self.audio.stop()


def parse_args():
    parser = argparse.ArgumentParser(description="WOW fishing automation")
    parser.add_argument("--config", default="config.json", help="path to config file")
    parser.add_argument("--list-devices", action="store_true", help="list audio devices")
    parser.add_argument("--record", action="store_true", help="record audio and exit")
    parser.add_argument(
        "--record-seconds",
        type=float,
        default=8.0,
        help="record duration in seconds",
    )
    parser.add_argument(
        "--record-out",
        default="recordings/hook.wav",
        help="record output wav path",
    )
    parser.add_argument(
        "--capture-bobber",
        action="store_true",
        help="capture bobber template and exit",
    )
    parser.add_argument(
        "--capture-size",
        type=int,
        default=72,
        help="capture size in pixels",
    )
    parser.add_argument(
        "--capture-out",
        default="assets/bobber_template.png",
        help="capture output png path",
    )
    parser.add_argument(
        "--capture-timeout",
        type=float,
        default=10.0,
        help="capture click timeout in seconds",
    )
    parser.add_argument(
        "--capture-region",
        action="store_true",
        help="interactively pick search region (two clicks) and exit",
    )
    parser.add_argument(
        "--region-timeout",
        type=float,
        default=15.0,
        help="timeout per click when capturing region",
    )
    parser.add_argument("--once", action="store_true", help="run only one loop")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.list_devices:
        print(sd.query_devices())
        return
    config = load_config(args.config)
    if args.record:
        audio_cfg = AudioConfig(**config["audio"])
        record_audio(audio_cfg, args.record_seconds, args.record_out)
        return
    if args.capture_region:
        try:
            region = capture_region(args.region_timeout)
            print(json.dumps(region))
        except Exception as exc:
            print(f"[region] error: {exc}")
            raise SystemExit(1)
        return
    if args.capture_bobber:
        try:
            capture_bobber(args.capture_size, args.capture_out, args.capture_timeout)
        except Exception as exc:
            print(f"[capture] error: {exc}")
            raise SystemExit(1)
        return
    bot = FishingBot(config)
    bot.run(once=args.once)


if __name__ == "__main__":
    main()
