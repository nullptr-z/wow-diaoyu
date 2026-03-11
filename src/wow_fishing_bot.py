#!/usr/bin/env python3
import argparse
import copy
import json
import os
import queue
import sys
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass

# Force line-buffered stdout so logs appear in real time when piped
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

import cv2
import numpy as np
import sounddevice as sd
from mss import mss
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController, Listener as MouseListener

DEFAULT_CONFIG = {
    "cast_key": "1",
    "cast_delay_sec": 1.5,
    "loot_delay_sec": 2.5,
    "audio": {
        "sample_rate": 44100,
        "fft_size": 2048,
        "freq_target_hz": 1200,
        "freq_band_hz": 300,
        "ratio_threshold": 0.35,
        "consecutive_hits": 2,
        "wasapi_loopback": False,
        "device": None,
        "spike_factor": 2.0,
        "spike_window": 20,
    },
    "vision": {
        "template_path": "assets/bobber_template.png",
        "extra_templates": [],
        "search_region": {
            "left": 200,
            "top": 200,
            "width": 800,
            "height": 600,
        },
        "match_threshold": 0.55,
        "use_edge_detection": True,
        "use_orb": True,
        "orb_min_matches": 6,
        "glow_check": False,
        "glow_brightness_threshold": 200,
        "glow_ratio_threshold": 0.15,
        "blacklist_templates": [],
        "blacklist_threshold": 0.6,
    },
    "click": {
        "move_delay_sec": 0.05,
        "post_click_delay_sec": 0.2,
    },
    "loop": {
        "idle_sleep_sec": 0.05,
        "max_wait_sec": 25,
        "min_listen_sec": 4.0,
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


def _float_or(value, default):
    if value == "" or value is None:
        return float(default)
    return float(value)


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
    spike_factor: float = 2.0
    spike_window: int = 20


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
        self.recent_scores = deque(maxlen=config.spike_window)

    def start(self):
        if self.stream is not None:
            return
        print(f"[audio] config: rate={self.config.sample_rate}, fft={self.config.fft_size}, "
              f"target={self.config.freq_target_hz}Hz, band={self.config.freq_band_hz}Hz, "
              f"threshold={self.config.ratio_threshold}, hits={self.config.consecutive_hits}, "
              f"loopback={self.config.wasapi_loopback}, device={self.config.device}")
        if self.config.wasapi_loopback:
            print("[audio] starting WASAPI loopback...")
            self._start_loopback()
        else:
            print(f"[audio] starting sounddevice InputStream, device={self.config.device}")
            self.stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                blocksize=self.config.fft_size,
                channels=1,
                callback=self._callback,
                device=self.config.device,
            )
            self.stream.start()
        print("[audio] stream started OK")

    def _start_loopback(self):
        p, dev, pyaudio = _find_pyaudio_loopback()
        if p is None:
            raise RuntimeError(
                "WASAPI loopback not available. Install pyaudiowpatch:\n"
                "  pip install pyaudiowpatch"
            )
        print(f"[audio] loopback device: {dev['name']}, channels={dev['maxInputChannels']}, rate={int(dev['defaultSampleRate'])}")
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
            print(f"[audio] resampling: loopback rate {self._loopback_rate} → config rate {self.config.sample_rate}")
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
        flushed = 0
        while True:
            try:
                self.queue.get_nowait()
                flushed += 1
            except queue.Empty:
                break
        self.hit_count = 0
        self.recent_scores.clear()
        print(f"[audio] flushed {flushed} chunks, hit_count reset")

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

    def poll_score(self, timeout_sec):
        """Get the score of the next audio chunk, or None if no data."""
        try:
            chunk = self.queue.get(timeout=timeout_sec)
        except queue.Empty:
            return None
        return self._score_chunk(chunk)

    def poll_hook(self, timeout_sec, threshold_override=None):
        threshold = threshold_override if threshold_override is not None else self.config.ratio_threshold
        try:
            chunk = self.queue.get(timeout=timeout_sec)
        except queue.Empty:
            return False
        score = self._score_chunk(chunk)

        # Spike detection: score must also be a significant spike above recent history
        is_spike = True
        if self.config.spike_factor > 0 and len(self.recent_scores) >= 3:
            recent_mean = np.mean(self.recent_scores)
            recent_std = max(np.std(self.recent_scores), 0.01)
            spike_threshold = recent_mean + self.config.spike_factor * recent_std
            is_spike = score >= spike_threshold
            if score >= threshold and not is_spike:
                print(f"[audio] score={score:.3f} >= {threshold:.3f} but NOT a spike "
                      f"(need {spike_threshold:.3f}, recent_mean={recent_mean:.3f})")

        self.recent_scores.append(score)

        if score >= threshold and is_spike:
            self.hit_count += 1
            print(f"[audio] score={score:.3f} >= {threshold:.3f} (spike OK) → hit {self.hit_count}/{self.config.consecutive_hits}")
        else:
            if self.hit_count > 0:
                print(f"[audio] score={score:.3f} < {threshold:.3f} → hit_count reset (was {self.hit_count})")
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
    """Show a fullscreen transparent overlay and let user drag to select a region."""
    import tkinter as tk

    result = {}

    root = tk.Tk()
    root.attributes("-topmost", True)
    root.overrideredirect(True)

    # Fullscreen
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{sw}x{sh}+0+0")

    # Semi-transparent overlay
    if sys.platform == "darwin":
        root.attributes("-transparent", True)
        root.config(bg="systemTransparent")
        canvas = tk.Canvas(root, width=sw, height=sh, highlightthickness=0, bg="systemTransparent")
        # Draw a semi-transparent dark overlay using stipple
        canvas.create_rectangle(0, 0, sw, sh, fill="gray", stipple="gray25", outline="")
    else:
        root.attributes("-alpha", 0.3)
        root.config(bg="black")
        canvas = tk.Canvas(root, width=sw, height=sh, highlightthickness=0, bg="black")

    canvas.pack(fill=tk.BOTH, expand=True)

    # Instruction text
    canvas.create_text(
        sw // 2, 40,
        text="拖拽鼠标框选区域，松开确认，ESC 取消",
        fill="white", font=("sans-serif", 18, "bold"),
    )

    start_x = 0
    start_y = 0
    rect_id = None

    def on_press(event):
        nonlocal start_x, start_y, rect_id
        start_x = event.x
        start_y = event.y
        if rect_id:
            canvas.delete(rect_id)
        rect_id = canvas.create_rectangle(
            start_x, start_y, start_x, start_y,
            outline="red", width=2,
        )

    def on_drag(event):
        nonlocal rect_id
        if rect_id:
            canvas.coords(rect_id, start_x, start_y, event.x, event.y)

    def on_release(event):
        x1, y1 = start_x, start_y
        x2, y2 = event.x, event.y
        left = min(x1, x2)
        top = min(y1, y2)
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        if width > 5 and height > 5:
            result["region"] = {"left": left, "top": top, "width": width, "height": height}
        root.destroy()

    def on_escape(event):
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)

    root.mainloop()

    if "region" not in result:
        raise ValueError("region selection cancelled")

    region = result["region"]
    print(f"[region] result: left={region['left']}, top={region['top']}, width={region['width']}, height={region['height']}")
    return region


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
    extra_templates: list
    search_left: int
    search_top: int
    search_width: int
    search_height: int
    match_threshold: float
    use_edge_detection: bool
    use_orb: bool
    orb_min_matches: int
    glow_check: bool
    glow_brightness_threshold: int
    glow_ratio_threshold: float
    blacklist_templates: list
    blacklist_threshold: float


class VisionLocator:
    def __init__(self, config: VisionConfig):
        self.config = config
        self.sct = mss()
        # Load primary template
        self.template = cv2.imread(config.template_path, cv2.IMREAD_GRAYSCALE)
        if self.template is None:
            raise FileNotFoundError(f"template not found: {config.template_path}")
        self.template_h, self.template_w = self.template.shape
        # Build list of all templates (primary + extras for different angles/views)
        self.templates = [(config.template_path, self.template)]
        for path in config.extra_templates:
            tmpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if tmpl is None:
                print(f"[vision] WARNING: extra template not found: {path}")
            else:
                self.templates.append((path, tmpl))
                print(f"[vision] loaded extra template: {path}")
        print(f"[vision] {len(self.templates)} bobber template(s) loaded")
        # Precompute edge templates for edge-based matching
        if config.use_edge_detection:
            self.templates_edges = [(p, cv2.Canny(t, 50, 150)) for p, t in self.templates]
            print(f"[vision] edge detection enabled")
        else:
            self.templates_edges = None
        # Precompute ORB keypoints and descriptors for feature matching
        if config.use_orb:
            self.orb = cv2.ORB_create(nfeatures=500)
            self.bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
            self.templates_orb = []
            for path, tmpl in self.templates:
                kp, des = self.orb.detectAndCompute(tmpl, None)
                if des is not None and len(kp) >= 2:
                    th, tw = tmpl.shape[:2]
                    self.templates_orb.append((path, kp, des, tw, th))
                else:
                    print(f"[vision] ORB: too few features in {path}, skipping")
            print(f"[vision] ORB enabled ({len(self.templates_orb)} template(s) with features)")
        else:
            self.orb = None
            self.templates_orb = []
        # Load blacklist templates
        self.blacklist = []
        for path in config.blacklist_templates:
            tmpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if tmpl is None:
                print(f"[vision] WARNING: blacklist template not found: {path}")
            else:
                self.blacklist.append((path, tmpl))
                print(f"[vision] loaded blacklist template: {path}")
        if self.blacklist:
            print(f"[vision] {len(self.blacklist)} blacklist template(s) loaded")

    def _grab_region(self):
        region = {
            "left": self.config.search_left,
            "top": self.config.search_top,
            "width": self.config.search_width,
            "height": self.config.search_height,
        }
        frame = np.array(self.sct.grab(region))
        return region, frame

    def _multiscale_match(self, gray, template):
        """Run multi-scale template matching, return (best_val, best_loc, best_tw, best_th, best_scale)."""
        best_val = -1
        best_loc = None
        best_tw = template.shape[1]
        best_th = template.shape[0]
        best_scale = 1.0
        th_orig, tw_orig = template.shape[:2]
        for scale in (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3):
            tw = int(tw_orig * scale)
            th = int(th_orig * scale)
            if tw < 10 or th < 10 or tw >= gray.shape[1] or th >= gray.shape[0]:
                continue
            scaled = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(gray, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_val:
                best_val = max_val
                best_loc = max_loc
                best_tw = tw
                best_th = th
                best_scale = scale
        return best_val, best_loc, best_tw, best_th, best_scale

    def _orb_match(self, gray):
        """ORB feature matching across all templates. Returns (cx, cy, score, path) or None."""
        if not self.orb or not self.templates_orb:
            return None
        kp_scene, des_scene = self.orb.detectAndCompute(gray, None)
        if des_scene is None or len(kp_scene) < 2:
            return None

        best_result = None
        best_good_count = 0
        for path, kp_tmpl, des_tmpl, tw, th in self.templates_orb:
            matches = self.bf.knnMatch(des_tmpl, des_scene, k=2)
            # Lowe's ratio test
            good = []
            for m_pair in matches:
                if len(m_pair) == 2:
                    m, n = m_pair
                    if m.distance < 0.75 * n.distance:
                        good.append(m)
            if len(good) < self.config.orb_min_matches:
                continue
            if len(good) > best_good_count:
                # Compute centroid of matched scene keypoints
                pts = np.array([kp_scene[m.trainIdx].pt for m in good])
                cx = int(np.mean(pts[:, 0]))
                cy = int(np.mean(pts[:, 1]))
                # Estimate bounding box from keypoint spread
                spread_x = int(np.std(pts[:, 0]) * 2) or tw // 2
                spread_y = int(np.std(pts[:, 1]) * 2) or th // 2
                # Score: ratio of good matches to template descriptors
                score = len(good) / len(des_tmpl)
                best_result = (cx, cy, spread_x, spread_y, score, path)
                best_good_count = len(good)
        return best_result

    def _check_glow(self, gray, cx, cy, radius):
        """Check for white glow ring around the matched bobber position."""
        h, w = gray.shape
        outer_r = int(radius * 1.5)
        inner_r = radius
        y_coords, x_coords = np.ogrid[:h, :w]
        dist_sq = (x_coords - cx) ** 2 + (y_coords - cy) ** 2
        ring_mask = (dist_sq >= inner_r ** 2) & (dist_sq <= outer_r ** 2)
        ring_pixels = gray[ring_mask]
        if len(ring_pixels) == 0:
            return 0.0
        bright_ratio = np.mean(ring_pixels >= self.config.glow_brightness_threshold)
        return bright_ratio

    def find(self):
        region, frame = self._grab_region()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)

        best_val = -1
        best_loc = None
        best_tw = self.template_w
        best_th = self.template_h
        best_scale = 1.0
        match_mode = "grayscale"
        match_tmpl = ""
        threshold = self.config.match_threshold

        # Phase 1: grayscale template matching — early exit if score is high enough
        for path, tmpl in self.templates:
            g_val, g_loc, g_tw, g_th, g_scale = self._multiscale_match(gray, tmpl)
            if g_val > best_val:
                best_val, best_loc, best_tw, best_th, best_scale = g_val, g_loc, g_tw, g_th, g_scale
                match_mode = "grayscale"
                match_tmpl = path
            if best_val >= threshold:
                break  # good enough, skip remaining templates

        # Phase 2: edge matching — only if grayscale didn't reach threshold
        if best_val < threshold and self.templates_edges is not None:
            gray_edges = cv2.Canny(gray, 50, 150)
            for path, tmpl_edge in self.templates_edges:
                e_val, e_loc, e_tw, e_th, e_scale = self._multiscale_match(gray_edges, tmpl_edge)
                if e_val > best_val:
                    best_val, best_loc, best_tw, best_th, best_scale = e_val, e_loc, e_tw, e_th, e_scale
                    match_mode = "edge"
                    match_tmpl = path
                if best_val >= threshold:
                    break

        # Phase 3: ORB — only if template matching failed
        local_cx, local_cy, glow_radius = None, None, 0
        if best_val >= threshold:
            local_cx = best_loc[0] + best_tw // 2
            local_cy = best_loc[1] + best_th // 2
            glow_radius = max(best_tw, best_th) // 2
            final_score = best_val
            final_mode = f"template/{match_mode}"
            print(f"[vision] template match ({match_mode}, {os.path.basename(match_tmpl)}): "
                  f"score={best_val:.4f}, scale={best_scale:.1f}x")
        else:
            orb_result = self._orb_match(gray)
            if orb_result is not None:
                local_cx, local_cy = orb_result[0], orb_result[1]
                glow_radius = max(orb_result[2], orb_result[3])
                final_score = orb_result[4]
                final_mode = "orb"
                print(f"[vision] ORB match ({os.path.basename(orb_result[5])}): "
                      f"score={final_score:.3f}, pos=({local_cx},{local_cy})")
            else:
                print(f"[vision] REJECTED: no match (template best={best_val:.4f}, ORB=none)")
                return None

        # Glow check: verify white glow ring around bobber (own bobber has glow, others don't)
        if self.config.glow_check:
            glow_ratio = self._check_glow(gray, local_cx, local_cy, glow_radius)
            print(f"[vision] glow check: bright_ratio={glow_ratio:.3f}, "
                  f"threshold={self.config.glow_ratio_threshold}")
            if glow_ratio < self.config.glow_ratio_threshold:
                print(f"[vision] REJECTED: no glow detected (not own bobber?)")
                return None

        x = region["left"] + local_cx
        y = region["top"] + local_cy
        print(f"[vision] MATCHED ({final_mode}): clicking at ({x}, {y}), score={final_score:.3f}")
        return (x, y, final_score)

    def check_blacklist(self):
        """Check if any blacklisted icon is visible in the search region. Returns matched path or None."""
        if not self.blacklist:
            return None
        region, frame = self._grab_region()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        for path, tmpl in self.blacklist:
            result = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val >= self.config.blacklist_threshold:
                print(f"[vision] BLACKLIST HIT: {path} (score={max_val:.4f} >= {self.config.blacklist_threshold})")
                return path
        return None


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
            extra_templates=config["vision"].get("extra_templates", []),
            search_left=config["vision"]["search_region"]["left"],
            search_top=config["vision"]["search_region"]["top"],
            search_width=config["vision"]["search_region"]["width"],
            search_height=config["vision"]["search_region"]["height"],
            match_threshold=config["vision"]["match_threshold"],
            use_edge_detection=config["vision"].get("use_edge_detection", True),
            use_orb=config["vision"].get("use_orb", True),
            orb_min_matches=config["vision"].get("orb_min_matches", 6),
            glow_check=config["vision"].get("glow_check", False),
            glow_brightness_threshold=config["vision"].get("glow_brightness_threshold", 200),
            glow_ratio_threshold=config["vision"].get("glow_ratio_threshold", 0.15),
            blacklist_templates=config["vision"].get("blacklist_templates", []),
            blacklist_threshold=config["vision"].get("blacklist_threshold", 0.6),
        )
        self.audio = AudioDetector(audio_cfg)
        self.vision = VisionLocator(vision_cfg)
        self.input = InputController(
            config["cast_key"],
            config["click"]["move_delay_sec"],
            config["click"]["post_click_delay_sec"],
        )
        defaults = DEFAULT_CONFIG
        self.cast_delay_sec = _float_or(config["cast_delay_sec"], defaults["cast_delay_sec"])
        self.loot_delay_sec = _float_or(config.get("loot_delay_sec", 2.5), defaults["loot_delay_sec"])
        self.max_wait_sec = _float_or(config["loop"]["max_wait_sec"], defaults["loop"]["max_wait_sec"])
        self.idle_sleep_sec = _float_or(config["loop"]["idle_sleep_sec"], defaults["loop"]["idle_sleep_sec"])
        self.min_listen_sec = _float_or(config["loop"].get("min_listen_sec", 4.0), defaults["loop"]["min_listen_sec"])

    def run(self, once=False, countdown=5):
        print(f"[bot] starting in {countdown} seconds, switch to game window now!")
        for i in range(countdown, 0, -1):
            print(f"  {i}...")
            time.sleep(1)
        self.audio.start()
        print("[bot] started, press Ctrl+C to stop.")
        cast_count = 0
        try:
            while True:
                cast_count += 1
                print(f"[bot] ===== cast #{cast_count} =====")
                self.input.cast()
                print(f"[bot] key pressed, waiting {self.cast_delay_sec:.1f}s for bobber to land...")
                time.sleep(self.cast_delay_sec)

                # Blacklist check: recast if problematic icon detected (e.g. cursor overlapping bobber)
                bl_hit = self.vision.check_blacklist()
                if bl_hit is not None:
                    print(f"[bot] blacklist icon detected ({bl_hit}), recasting...")
                    continue

                self.audio.flush()

                min_listen = self.min_listen_sec
                print(f"[bot] listening for hook sound (min {min_listen:.1f}s, max {self.max_wait_sec}s)...")
                listen_start = time.monotonic()
                deadline = listen_start + self.max_wait_sec
                hooked = False
                poll_count = 0
                baseline_scores = []
                baseline_mean = 0.0
                baseline_ready = False
                while time.monotonic() < deadline:
                    poll_count += 1
                    elapsed = time.monotonic() - listen_start

                    # During min_listen, collect baseline scores instead of checking for hook
                    if elapsed < min_listen:
                        score = self.audio.poll_score(timeout_sec=0.25)
                        if score is not None:
                            baseline_scores.append(score)
                    else:
                        # Calculate baseline once when min_listen expires
                        if not baseline_ready:
                            if baseline_scores:
                                baseline_mean = np.mean(baseline_scores)
                                baseline_std = np.std(baseline_scores)
                                # Dynamic threshold: baseline + 2*std, but at least the configured threshold
                                dynamic_threshold = max(
                                    self.audio.config.ratio_threshold,
                                    baseline_mean + max(2.0 * baseline_std, 0.1),
                                )
                            else:
                                dynamic_threshold = self.audio.config.ratio_threshold
                            baseline_ready = True
                            print(f"[audio] baseline: mean={baseline_mean:.3f}, "
                                  f"dynamic_threshold={dynamic_threshold:.3f} "
                                  f"(from {len(baseline_scores)} samples)")
                            self.audio.hit_count = 0

                        if self.audio.poll_hook(timeout_sec=0.25, threshold_override=dynamic_threshold):
                            print(f"[audio] HOOK TRIGGERED after {elapsed:.1f}s ({poll_count} polls)")
                            hooked = True
                            break
                    time.sleep(self.idle_sleep_sec)

                if not hooked:
                    elapsed = time.monotonic() - listen_start
                    print(f"[bot] no hook detected after {elapsed:.1f}s ({poll_count} polls), recast")
                    if once:
                        return
                    continue

                print("[bot] hook detected! looking for bobber...")
                match = self.vision.find()
                if match is None:
                    print("[bot] hook detected, but no bobber match — skipping click, recast")
                    print(f"[bot] cooldown {self.cast_delay_sec:.1f}s to avoid spam")
                    time.sleep(self.cast_delay_sec)
                    if once:
                        return
                    continue

                x, y, score = match
                print(f"[bot] click at ({x}, {y}), score={score:.3f}")
                self.input.click(x, y)
                print(f"[bot] waiting {self.loot_delay_sec:.1f}s for loot pickup")
                time.sleep(self.loot_delay_sec)
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
    parser.add_argument(
        "--capture-blacklist",
        action="store_true",
        help="capture a blacklist template icon and exit",
    )
    parser.add_argument(
        "--blacklist-size",
        type=int,
        default=48,
        help="blacklist capture size in pixels",
    )
    parser.add_argument(
        "--blacklist-out",
        default="assets/blacklist_cursor.png",
        help="blacklist capture output png path",
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
    if args.capture_blacklist:
        try:
            capture_bobber(args.blacklist_size, args.blacklist_out, args.capture_timeout)
            print(f"[blacklist] template saved. Add '{args.blacklist_out}' to config vision.blacklist_templates")
        except Exception as exc:
            print(f"[capture] error: {exc}")
            raise SystemExit(1)
        return
    bot = FishingBot(config)
    bot.run(once=args.once)


if __name__ == "__main__":
    main()
