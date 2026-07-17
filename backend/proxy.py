#!/usr/bin/env python3
"""
proxy.py — Transparent HEVC→H.264 Transcoding Reverse Proxy
=============================================================

A single-file, production-grade HTTP reverse proxy that sits in front of a
media server (Jellyfin / Plex / Emby / any generic HTTP media origin) and
transparently transcodes H.265/HEVC video into H.264/AVC in real time for
clients that cannot play HEVC natively.

    Client  --->  proxy.py  --->  Jellyfin / Plex / Emby / Generic HTTP

Design goals
------------
* Fully asynchronous (FastAPI + Uvicorn + httpx.AsyncClient + asyncio subprocess).
* Zero temp files, zero full-body buffering — everything is streamed through
  OS pipes and async generators with sensible chunk sizes and backpressure.
* Codec-aware decision engine: pass H.264 straight through, transcode HEVC,
  probe when unknown.
* Hardware-acceleration aware (NVENC / QSV / VAAPI / AMF / VideoToolbox),
  with automatic fallback to libx264.
* Operationally complete: session tracking, Prometheus metrics, structured
  JSON logs, health/config/hardware/stats endpoints, graceful shutdown,
  bounded concurrency for transcodes, basic security controls.

Run
---
    export MEDIA_SERVER=http://127.0.0.1:8096
    python3 proxy.py

Then point your client at http://<proxy-host>:<port>/ instead of the media
server directly.

This file is intentionally organized into single-responsibility classes even
though it lives in one module, per the project's architecture requirements.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Deque, Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, PlainTextResponse
from starlette.background import BackgroundTask

try:
    import uvicorn
except ImportError:  # pragma: no cover - uvicorn is required to actually serve
    uvicorn = None  # type: ignore


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Config:
    """Central runtime configuration, populated from environment variables."""

    media_server: str = field(default_factory=lambda: os.environ.get(
        "MEDIA_SERVER", "http://127.0.0.1:8096"))
    media_token: str = field(default_factory=lambda: os.environ.get("MEDIA_TOKEN", ""))

    ffmpeg_path: str = field(default_factory=lambda: os.environ.get(
        "FFMPEG_PATH", shutil.which("ffmpeg") or "ffmpeg"))
    ffprobe_path: str = field(default_factory=lambda: os.environ.get(
        "FFPROBE_PATH", shutil.which("ffprobe") or "ffprobe"))

    host: str = field(default_factory=lambda: os.environ.get("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8080))

    cache_size: int = field(default_factory=lambda: _env_int("CACHE_SIZE", 512))
    cache_ttl: float = field(default_factory=lambda: _env_float("CACHE_TTL", 300.0))

    max_transcodes: int = field(default_factory=lambda: _env_int("MAX_TRANSCODES", 4))

    default_preset: str = field(default_factory=lambda: os.environ.get(
        "DEFAULT_PRESET", "veryfast"))
    default_crf: int = field(default_factory=lambda: _env_int("DEFAULT_CRF", 23))
    default_bitrate: str = field(default_factory=lambda: os.environ.get(
        "DEFAULT_BITRATE", ""))  # empty => CRF mode instead of CBR/VBR

    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    gpu_priority: str = field(default_factory=lambda: os.environ.get(
        "GPU_PRIORITY", "nvenc,qsv,vaapi,videotoolbox,amf,software"))
    thread_count: int = field(default_factory=lambda: _env_int(
        "THREAD_COUNT", os.cpu_count() or 4))

    chunk_size: int = field(default_factory=lambda: _env_int("CHUNK_SIZE", 256 * 1024))

    api_key: str = field(default_factory=lambda: os.environ.get("API_KEY", ""))
    allowed_origins: Tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()))
    rate_limit_per_min: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MIN", 600))

    connect_timeout: float = field(default_factory=lambda: _env_float("CONNECT_TIMEOUT", 10.0))
    upstream_http2: bool = field(default_factory=lambda: _env_bool("UPSTREAM_HTTP2", True))

    def gpu_order(self) -> List[str]:
        return [p.strip() for p in self.gpu_priority.split(",") if p.strip()]


CONFIG = Config()


# ═══════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════

class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(CONFIG.log_level.upper())
        logger.propagate = False
    return logger


LOG = build_logger("proxy")


def log_event(level: int, message: str, **fields: Any) -> None:
    LOG.log(level, message, extra={"extra_fields": fields})


# ═══════════════════════════════════════════════════════════════════════════
# Metrics
# ═══════════════════════════════════════════════════════════════════════════

class MetricsCollector:
    """
    Lightweight, dependency-free Prometheus-style metrics collector.

    Avoids a hard dependency on `prometheus_client` so this file remains
    self-contained; exposes a `/metrics` endpoint in the Prometheus text
    exposition format.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.total_requests = 0
        self.active_streams = 0
        self.current_transcodes = 0
        self.peak_transcodes = 0
        self.ffmpeg_failures = 0
        self.client_disconnects = 0
        self.bytes_streamed = 0
        self._startup_times: Deque[float] = deque(maxlen=200)
        self._bitrates: Deque[float] = deque(maxlen=200)
        self._fps_samples: Deque[float] = deque(maxlen=200)

    async def inc_requests(self) -> None:
        async with self._lock:
            self.total_requests += 1

    async def stream_started(self) -> None:
        async with self._lock:
            self.active_streams += 1

    async def stream_ended(self) -> None:
        async with self._lock:
            self.active_streams = max(0, self.active_streams - 1)

    async def transcode_started(self, startup_seconds: float) -> None:
        async with self._lock:
            self.current_transcodes += 1
            self.peak_transcodes = max(self.peak_transcodes, self.current_transcodes)
            self._startup_times.append(startup_seconds)

    async def transcode_ended(self) -> None:
        async with self._lock:
            self.current_transcodes = max(0, self.current_transcodes - 1)

    async def record_bitrate(self, kbps: float) -> None:
        async with self._lock:
            self._bitrates.append(kbps)

    async def record_fps(self, fps: float) -> None:
        async with self._lock:
            self._fps_samples.append(fps)

    async def add_bytes(self, n: int) -> None:
        async with self._lock:
            self.bytes_streamed += n

    async def inc_ffmpeg_failure(self) -> None:
        async with self._lock:
            self.ffmpeg_failures += 1

    async def inc_disconnect(self) -> None:
        async with self._lock:
            self.client_disconnects += 1

    def _avg(self, dq: Deque[float]) -> float:
        return (sum(dq) / len(dq)) if dq else 0.0

    async def snapshot(self) -> Dict[str, Any]:
        async with self._lock:
            return {
                "total_requests": self.total_requests,
                "active_streams": self.active_streams,
                "current_transcodes": self.current_transcodes,
                "peak_transcodes": self.peak_transcodes,
                "average_startup_seconds": round(self._avg(self._startup_times), 3),
                "average_bitrate_kbps": round(self._avg(self._bitrates), 2),
                "average_fps": round(self._avg(self._fps_samples), 2),
                "bytes_streamed": self.bytes_streamed,
                "ffmpeg_failures": self.ffmpeg_failures,
                "client_disconnects": self.client_disconnects,
            }

    async def prometheus_text(self) -> str:
        s = await self.snapshot()
        lines = [
            "# HELP proxy_total_requests Total HTTP requests handled",
            "# TYPE proxy_total_requests counter",
            f"proxy_total_requests {s['total_requests']}",
            "# HELP proxy_active_streams Currently active streams",
            "# TYPE proxy_active_streams gauge",
            f"proxy_active_streams {s['active_streams']}",
            "# HELP proxy_current_transcodes Currently running ffmpeg transcodes",
            "# TYPE proxy_current_transcodes gauge",
            f"proxy_current_transcodes {s['current_transcodes']}",
            "# HELP proxy_peak_transcodes Peak concurrent transcodes observed",
            "# TYPE proxy_peak_transcodes counter",
            f"proxy_peak_transcodes {s['peak_transcodes']}",
            "# HELP proxy_average_startup_seconds Average ffmpeg startup latency",
            "# TYPE proxy_average_startup_seconds gauge",
            f"proxy_average_startup_seconds {s['average_startup_seconds']}",
            "# HELP proxy_average_bitrate_kbps Average observed output bitrate",
            "# TYPE proxy_average_bitrate_kbps gauge",
            f"proxy_average_bitrate_kbps {s['average_bitrate_kbps']}",
            "# HELP proxy_average_fps Average observed encode fps",
            "# TYPE proxy_average_fps gauge",
            f"proxy_average_fps {s['average_fps']}",
            "# HELP proxy_bytes_streamed_total Total bytes streamed to clients",
            "# TYPE proxy_bytes_streamed_total counter",
            f"proxy_bytes_streamed_total {s['bytes_streamed']}",
            "# HELP proxy_ffmpeg_failures_total Total ffmpeg process failures",
            "# TYPE proxy_ffmpeg_failures_total counter",
            f"proxy_ffmpeg_failures_total {s['ffmpeg_failures']}",
            "# HELP proxy_client_disconnects_total Total client-initiated disconnects",
            "# TYPE proxy_client_disconnects_total counter",
            f"proxy_client_disconnects_total {s['client_disconnects']}",
        ]
        return "\n".join(lines) + "\n"


METRICS = MetricsCollector()


# ═══════════════════════════════════════════════════════════════════════════
# Cache Manager (LRU + TTL) for media metadata
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class MediaMetadata:
    """Probed information about a media item."""

    codec: str = "unknown"
    codec_tag: str = ""
    profile: str = ""
    width: int = 0
    height: int = 0
    bitrate_kbps: float = 0.0
    duration_seconds: float = 0.0
    fps: float = 0.0
    container: str = ""
    audio_codec: str = ""
    subtitle_tracks: List[str] = field(default_factory=list)
    is_hdr: bool = False
    probed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


class CacheManager:
    """A simple async-safe LRU cache with per-entry TTL for probed metadata."""

    def __init__(self, max_size: int, ttl: float) -> None:
        self.max_size = max_size
        self.ttl = ttl
        self._store: "OrderedDict[str, MediaMetadata]" = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[MediaMetadata]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.time() - entry.probed_at > self.ttl:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return entry

    async def set(self, key: str, value: MediaMetadata) -> None:
        async with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)

    async def stats(self) -> Dict[str, Any]:
        async with self._lock:
            return {"size": len(self._store), "max_size": self.max_size, "ttl": self.ttl}


CACHE = CacheManager(CONFIG.cache_size, CONFIG.cache_ttl)


# ═══════════════════════════════════════════════════════════════════════════
# Hardware Detection
# ═══════════════════════════════════════════════════════════════════════════

class HardwareDetector:
    """
    Detects which hardware-accelerated encoders ffmpeg was built with and
    which are actually usable on this host, caching the result for the
    lifetime of the process.
    """

    _ENCODER_MAP = {
        "nvenc": "h264_nvenc",
        "qsv": "h264_qsv",
        "vaapi": "h264_vaapi",
        "amf": "h264_amf",
        "videotoolbox": "h264_videotoolbox",
    }

    def __init__(self, ffmpeg_path: str) -> None:
        self.ffmpeg_path = ffmpeg_path
        self._result: Optional[Dict[str, bool]] = None
        self._lock = asyncio.Lock()

    async def detect(self, force: bool = False) -> Dict[str, bool]:
        async with self._lock:
            if self._result is not None and not force:
                return self._result
            encoders_text = await self._list_encoders()
            result: Dict[str, bool] = {}
            for key, enc_name in self._ENCODER_MAP.items():
                compiled_in = enc_name in encoders_text
                result[key] = compiled_in and await self._is_actually_usable(key, enc_name)
            result["software"] = "libx264" in encoders_text
            self._result = result
            log_event(logging.INFO, "hardware_detected", **result)
            return result

    async def _is_actually_usable(self, accel: str, encoder: str) -> bool:
        """
        ffmpeg can be *compiled* with an encoder while the host has no usable
        device for it (no GPU, no /dev/dri, permission denied, etc). Rather
        than trusting `-encoders` alone, run a tiny real encode against a
        synthetic test source and confirm ffmpeg actually succeeds — this is
        what lets us fall back to libx264 automatically and correctly.
        """
        if accel in ("vaapi",) and not os.path.exists("/dev/dri/renderD128"):
            return False
        if accel == "nvenc" and not any(
            os.path.exists(p) for p in ("/dev/nvidia0", "/dev/nvidiactl")
        ):
            return False

        cmd = [self.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y"]
        if accel == "nvenc":
            cmd += ["-hwaccel", "cuda"]
        elif accel == "vaapi":
            cmd += ["-hwaccel", "vaapi", "-vaapi_device", "/dev/dri/renderD128"]
        cmd += ["-f", "lavfi", "-i", "testsrc=duration=0.5:size=64x64:rate=5",
                "-frames:v", "3", "-c:v", encoder, "-f", "null", "-"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            code = await asyncio.wait_for(proc.wait(), timeout=8.0)
            return code == 0
        except (asyncio.TimeoutError, OSError, FileNotFoundError):
            return False

    async def _list_encoders(self) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                self.ffmpeg_path, "-hide_banner", "-encoders",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            return stdout.decode(errors="ignore")
        except (FileNotFoundError, asyncio.TimeoutError, OSError) as exc:
            log_event(logging.WARNING, "ffmpeg_encoder_probe_failed", error=str(exc))
            return ""

    async def best_encoder(self, priority_order: List[str]) -> Tuple[str, str]:
        """Return (accel_name, encoder_binary) for the highest-priority available encoder."""
        available = await self.detect()
        for accel in priority_order:
            if accel == "software":
                continue
            if available.get(accel) and self._ENCODER_MAP.get(accel):
                return accel, self._ENCODER_MAP[accel]
        return "software", "libx264"


HARDWARE = HardwareDetector(CONFIG.ffmpeg_path)


# ═══════════════════════════════════════════════════════════════════════════
# Codec Detection / Media Inspection
# ═══════════════════════════════════════════════════════════════════════════

HEVC_TOKENS = {"hevc", "h265", "h.265", "hvc1", "hev1", "main10", "main 10", "main12"}
H264_TOKENS = {"h264", "avc", "avc1", "h.264"}


class CodecDetector:
    """Normalizes raw codec strings from various sources into a canonical form."""

    @staticmethod
    def classify(raw: str) -> str:
        if not raw:
            return "unknown"
        s = raw.strip().lower()
        if any(tok in s for tok in HEVC_TOKENS):
            return "hevc"
        if any(tok in s for tok in H264_TOKENS):
            return "h264"
        return raw.strip()

    @staticmethod
    def is_hevc(codec: str) -> bool:
        return CodecDetector.classify(codec) == "hevc"

    @staticmethod
    def is_h264(codec: str) -> bool:
        return CodecDetector.classify(codec) == "h264"


class MediaInspector:
    """
    Determines media codec/metadata using, in priority order:
      1. Cached metadata (CacheManager)
      2. Server-native metadata (Jellyfin/Plex/Emby JSON APIs), if reachable
      3. ffprobe against the upstream URL directly (authoritative fallback)
      4. MIME-type / container inspection as a last resort
    """

    def __init__(self, ffprobe_path: str, cache: CacheManager) -> None:
        self.ffprobe_path = ffprobe_path
        self.cache = cache

    async def inspect(self, url: str, headers: Dict[str, str]) -> MediaMetadata:
        cache_key = self._cache_key(url)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return cached

        metadata = await self._probe_with_ffprobe(url, headers)
        if metadata.codec == "unknown":
            metadata = self._infer_from_mimetype(url, metadata)

        await self.cache.set(cache_key, metadata)
        return metadata

    @staticmethod
    def _cache_key(url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        # Strip volatile auth/session query params from the cache key so the
        # same media item probed via different sessions hits the same entry.
        query = urllib.parse.parse_qsl(parsed.query)
        stable_query = sorted((k, v) for k, v in query if k.lower() not in
                               {"api_key", "token", "x-emby-token", "x-plex-token"})
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                                         urllib.parse.urlencode(stable_query), ""))

    async def _probe_with_ffprobe(self, url: str, headers: Dict[str, str]) -> MediaMetadata:
        header_str = "".join(f"{k}: {v}\r\n" for k, v in headers.items()
                              if k.lower() in ("authorization", "cookie", "user-agent"))
        cmd = [
            self.ffprobe_path, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams",
            "-analyzeduration", "5000000", "-probesize", "5000000",
        ]
        if header_str:
            cmd += ["-headers", header_str]
        cmd += [url]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            data = json.loads(stdout.decode(errors="ignore") or "{}")
        except (asyncio.TimeoutError, json.JSONDecodeError, OSError, FileNotFoundError) as exc:
            log_event(logging.WARNING, "ffprobe_failed", url=url, error=str(exc))
            return MediaMetadata()

        return self._parse_ffprobe_json(data)

    @staticmethod
    def _parse_ffprobe_json(data: Dict[str, Any]) -> MediaMetadata:
        fmt = data.get("format", {}) or {}
        streams = data.get("streams", []) or []
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        subs = [s.get("tags", {}).get("language", s.get("codec_name", "sub"))
                for s in streams if s.get("codec_type") == "subtitle"]

        raw_codec = video.get("codec_name", "") or ""
        codec_tag = video.get("codec_tag_string", "") or ""
        profile = video.get("profile", "") or ""
        classify_input = " ".join([raw_codec, codec_tag, profile])
        codec = CodecDetector.classify(classify_input)

        fps = 0.0
        rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
        try:
            num, den = rate.split("/")
            fps = (float(num) / float(den)) if float(den) != 0 else 0.0
        except (ValueError, ZeroDivisionError):
            pass

        is_hdr = any(tok in (video.get("color_transfer", "") or "").lower()
                     for tok in ("smpte2084", "arib-std-b67")) or "10" in profile

        try:
            duration = float(fmt.get("duration", 0) or video.get("duration", 0) or 0)
        except ValueError:
            duration = 0.0
        try:
            bitrate_kbps = float(fmt.get("bit_rate", 0) or 0) / 1000.0
        except ValueError:
            bitrate_kbps = 0.0

        return MediaMetadata(
            codec=codec,
            codec_tag=codec_tag,
            profile=profile,
            width=int(video.get("width", 0) or 0),
            height=int(video.get("height", 0) or 0),
            bitrate_kbps=bitrate_kbps,
            duration_seconds=duration,
            fps=round(fps, 2),
            container=(fmt.get("format_name", "") or "").split(",")[0],
            audio_codec=audio.get("codec_name", "") or "",
            subtitle_tracks=[str(s) for s in subs],
            is_hdr=is_hdr,
        )

    @staticmethod
    def _infer_from_mimetype(url: str, metadata: MediaMetadata) -> MediaMetadata:
        ext = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lower().lstrip(".")
        container_map = {
            "mp4": "mp4", "m4v": "mp4", "mkv": "matroska", "avi": "avi",
            "mov": "mov", "webm": "webm", "ts": "mpegts", "m3u8": "hls", "mpd": "dash",
        }
        if ext in container_map and not metadata.container:
            metadata.container = container_map[ext]
        return metadata


INSPECTOR = MediaInspector(CONFIG.ffprobe_path, CACHE)


# ═══════════════════════════════════════════════════════════════════════════
# FFmpeg Pipeline
# ═══════════════════════════════════════════════════════════════════════════

QUALITY_HEIGHTS = {"240": 240, "360": 360, "480": 480, "720": 720, "1080": 1080}


@dataclass
class TranscodeOptions:
    """User/query-controlled transcode parameters."""

    preset: str = CONFIG.default_preset
    crf: int = CONFIG.default_crf
    bitrate: str = CONFIG.default_bitrate
    quality: Optional[str] = None
    audio_mode: str = "copy"          # copy | aac
    subtitle_mode: str = "copy"       # copy | burn | drop
    fps: Optional[float] = None
    gop: int = 48
    pixel_format: str = "yuv420p"
    threads: int = CONFIG.thread_count
    low_latency: bool = True
    start_time: float = 0.0          # seek offset in seconds, for range/scrub restarts
    output_format: str = "mp4"       # mp4 | mpegts

    @classmethod
    def from_query(cls, params: Dict[str, str]) -> "TranscodeOptions":
        opts = cls()
        if "preset" in params and params["preset"] in (
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow",
        ):
            opts.preset = params["preset"]
        if "crf" in params:
            with contextlib.suppress(ValueError):
                opts.crf = max(0, min(51, int(params["crf"])))
        if "bitrate" in params:
            opts.bitrate = params["bitrate"]
        if "quality" in params and params["quality"] in QUALITY_HEIGHTS:
            opts.quality = params["quality"]
        if "audio" in params and params["audio"] in ("copy", "aac"):
            opts.audio_mode = params["audio"]
        if "subtitles" in params and params["subtitles"] in ("copy", "burn", "drop"):
            opts.subtitle_mode = params["subtitles"]
        if "fps" in params:
            with contextlib.suppress(ValueError):
                opts.fps = float(params["fps"])
        if "gop" in params:
            with contextlib.suppress(ValueError):
                opts.gop = int(params["gop"])
        if "start" in params:
            with contextlib.suppress(ValueError):
                opts.start_time = max(0.0, float(params["start"]))
        if "format" in params and params["format"] in ("mp4", "mpegts"):
            opts.output_format = params["format"]
        return opts


class FFmpegPipeline:
    """
    Builds and manages a single ffmpeg process that reads an HTTP media
    stream on stdin and writes a transcoded H.264 stream on stdout.

    No temp files are ever created — input arrives via a pipe fed by an
    async task reading from the upstream httpx stream, and output is read
    chunk-by-chunk directly from the ffmpeg subprocess stdout pipe.
    """

    def __init__(self, ffmpeg_path: str, hardware: HardwareDetector, gpu_order: List[str]) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.hardware = hardware
        self.gpu_order = gpu_order

    async def build_command(self, opts: TranscodeOptions, source_url: str,
                             force_software: bool = False) -> List[str]:
        if force_software:
            accel, encoder = "software", "libx264"
        else:
            accel, encoder = await self.hardware.best_encoder(self.gpu_order)

        cmd: List[str] = [self.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y"]

        # Hardware decode/accel input options, where applicable.
        if accel == "nvenc":
            cmd += ["-hwaccel", "cuda"]
        elif accel == "qsv":
            cmd += ["-hwaccel", "qsv"]
        elif accel == "vaapi":
            cmd += ["-hwaccel", "vaapi", "-vaapi_device", "/dev/dri/renderD128"]

        if opts.start_time > 0:
            cmd += ["-ss", f"{opts.start_time:.3f}"]

        # Read directly from the upstream URL so ffmpeg handles HTTP itself
        # (keeps range/seek behavior simple and avoids double-buffering);
        # falls back to stdin piping when the caller passes "pipe:0".
        cmd += ["-i", source_url]

        if opts.low_latency:
            cmd += ["-fflags", "nobuffer", "-flags", "low_delay"]

        # Video filters: scaling for adaptive quality.
        vf_filters = []
        if opts.quality and opts.quality in QUALITY_HEIGHTS:
            target_h = QUALITY_HEIGHTS[opts.quality]
            vf_filters.append(f"scale=-2:{target_h}")
        if opts.subtitle_mode == "burn":
            vf_filters.append(f"subtitles='{source_url}'")
        if vf_filters:
            cmd += ["-vf", ",".join(vf_filters)]

        if opts.fps:
            cmd += ["-r", str(opts.fps)]

        # Video encoder selection.
        cmd += ["-c:v", encoder]
        if encoder == "libx264":
            cmd += ["-preset", opts.preset]
            if opts.bitrate:
                cmd += ["-b:v", opts.bitrate, "-maxrate", opts.bitrate, "-bufsize", opts.bitrate]
            else:
                cmd += ["-crf", str(opts.crf)]
        else:
            # Hardware encoders use their own preset/rate-control vocab.
            if opts.bitrate:
                cmd += ["-b:v", opts.bitrate]
            else:
                cmd += ["-b:v", "6M"]
            if accel == "nvenc":
                cmd += ["-preset", "p4", "-rc", "vbr"]
            elif accel == "qsv":
                cmd += ["-preset", "medium"]

        cmd += ["-g", str(opts.gop), "-pix_fmt", opts.pixel_format, "-profile:v", "high"]
        cmd += ["-threads", str(opts.threads)]

        # Audio handling.
        if opts.audio_mode == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "192k"]

        # Subtitle handling (copy only makes sense for MP4->MP4 text subs; ts drops them).
        if opts.subtitle_mode == "copy" and opts.output_format == "mp4":
            cmd += ["-c:s", "mov_text"]
        elif opts.subtitle_mode == "drop" or opts.subtitle_mode == "burn":
            cmd += ["-sn"]

        # Output container: fragmented MP4 (streamable, no seek-back needed)
        # or MPEG-TS, both writable to a pipe.
        if opts.output_format == "mpegts":
            cmd += ["-f", "mpegts", "pipe:1"]
        else:
            cmd += [
                "-movflags", "frag_keyframe+empty_moov+faststart+default_base_moof",
                "-f", "mp4", "pipe:1",
            ]

        return cmd


PIPELINE = FFmpegPipeline(CONFIG.ffmpeg_path, HARDWARE, CONFIG.gpu_order())


# ═══════════════════════════════════════════════════════════════════════════
# Session Manager
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Session:
    session_id: str
    client_ip: str
    media_url: str
    codec: str
    resolution: str
    bitrate_kbps: float
    started_at: float = field(default_factory=time.time)
    bytes_sent: int = 0
    ffmpeg_pid: Optional[int] = None
    current_fps: float = 0.0
    mode: str = "direct"  # direct | transcode

    def elapsed(self) -> float:
        return time.time() - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "client_ip": self.client_ip,
            "media_url": self.media_url,
            "codec": self.codec,
            "resolution": self.resolution,
            "bitrate_kbps": round(self.bitrate_kbps, 2),
            "elapsed_seconds": round(self.elapsed(), 1),
            "bytes_sent": self.bytes_sent,
            "ffmpeg_pid": self.ffmpeg_pid,
            "current_fps": round(self.current_fps, 2),
            "mode": self.mode,
        }


class SessionManager:
    """Tracks all active client sessions (direct-passthrough or transcode)."""

    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create(self, client_ip: str, media_url: str, codec: str,
                      resolution: str, bitrate_kbps: float, mode: str) -> Session:
        session = Session(
            session_id=str(uuid.uuid4()), client_ip=client_ip, media_url=media_url,
            codec=codec, resolution=resolution, bitrate_kbps=bitrate_kbps, mode=mode,
        )
        async with self._lock:
            self._sessions[session.session_id] = session
        return session

    async def update_bytes(self, session_id: str, n: int) -> None:
        async with self._lock:
            s = self._sessions.get(session_id)
            if s:
                s.bytes_sent += n

    async def set_pid(self, session_id: str, pid: int) -> None:
        async with self._lock:
            s = self._sessions.get(session_id)
            if s:
                s.ffmpeg_pid = pid

    async def set_fps(self, session_id: str, fps: float) -> None:
        async with self._lock:
            s = self._sessions.get(session_id)
            if s:
                s.current_fps = fps

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def list_sessions(self) -> List[Dict[str, Any]]:
        async with self._lock:
            return [s.to_dict() for s in self._sessions.values()]


SESSIONS = SessionManager()


# ═══════════════════════════════════════════════════════════════════════════
# Transcode Manager
# ═══════════════════════════════════════════════════════════════════════════

class TranscodeManager:
    """
    Owns the lifecycle of ffmpeg subprocesses: spawning, bounding concurrency,
    monitoring stderr for progress (fps/bitrate), and guaranteeing cleanup so
    no zombie processes are left behind even on client disconnect or crash.
    """

    def __init__(self, max_concurrent: int) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active: Dict[int, asyncio.subprocess.Process] = {}
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        await self._semaphore.acquire()

    def release(self) -> None:
        self._semaphore.release()

    async def spawn(self, cmd: List[str]) -> asyncio.subprocess.Process:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1 << 20,
        )
        async with self._lock:
            self._active[proc.pid] = proc
        log_event(logging.INFO, "ffmpeg_spawned", pid=proc.pid, cmd=" ".join(cmd))
        return proc

    async def terminate(self, proc: asyncio.subprocess.Process, grace: float = 3.0) -> Optional[int]:
        if proc.returncode is not None:
            await self._forget(proc.pid)
            return proc.returncode
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=grace)
        except asyncio.TimeoutError:
            log_event(logging.WARNING, "ffmpeg_force_kill", pid=proc.pid)
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=2.0)
        await self._forget(proc.pid)
        return proc.returncode

    async def _forget(self, pid: int) -> None:
        async with self._lock:
            self._active.pop(pid, None)

    async def active_count(self) -> int:
        async with self._lock:
            return len(self._active)

    async def shutdown_all(self) -> None:
        async with self._lock:
            procs = list(self._active.values())
        for proc in procs:
            await self.terminate(proc, grace=2.0)

    @staticmethod
    def parse_progress_line(line: str) -> Dict[str, float]:
        """Parse an ffmpeg stderr progress-ish line for fps/bitrate hints."""
        result: Dict[str, float] = {}
        fps_match = re.search(r"fps=\s*([\d.]+)", line)
        if fps_match:
            with contextlib.suppress(ValueError):
                result["fps"] = float(fps_match.group(1))
        bitrate_match = re.search(r"bitrate=\s*([\d.]+)kbits/s", line)
        if bitrate_match:
            with contextlib.suppress(ValueError):
                result["bitrate_kbps"] = float(bitrate_match.group(1))
        return result


TRANSCODER = TranscodeManager(CONFIG.max_transcodes)


# ═══════════════════════════════════════════════════════════════════════════
# HTTP client pool (upstream connection reuse)
# ═══════════════════════════════════════════════════════════════════════════

def build_http_client() -> httpx.AsyncClient:
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    timeout = httpx.Timeout(CONFIG.connect_timeout, read=None, write=30.0, pool=10.0)
    return httpx.AsyncClient(
        http2=CONFIG.upstream_http2, limits=limits, timeout=timeout, follow_redirects=False,
    )


HTTP_CLIENT: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    """Lazily build the shared upstream client.

    When this app is mounted under another FastAPI app (e.g. /px in
    app.py), its own lifespan may not run, so the module-global
    HTTP_CLIENT would stay None. Building it on first use keeps the
    proxy working either way.
    """
    global HTTP_CLIENT
    if HTTP_CLIENT is None:
        HTTP_CLIENT = build_http_client()
    return HTTP_CLIENT


# ═══════════════════════════════════════════════════════════════════════════
# Security helpers
# ═══════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Simple sliding-window rate limiter, per client IP."""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit = limit_per_minute
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, client_ip: str) -> bool:
        if self.limit <= 0:
            return True
        now = time.time()
        async with self._lock:
            window = self._hits.setdefault(client_ip, deque())
            while window and now - window[0] > 60.0:
                window.popleft()
            if len(window) >= self.limit:
                return False
            window.append(now)
            return True


RATE_LIMITER = RateLimiter(CONFIG.rate_limit_per_min)


def check_api_key(request: Request) -> None:
    if not CONFIG.api_key:
        return
    supplied = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if supplied != CONFIG.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def check_origin(request: Request) -> None:
    if CONFIG.allowed_origins == ("*",):
        return
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    if origin and not any(origin.startswith(o) for o in CONFIG.allowed_origins):
        raise HTTPException(status_code=403, detail="Origin not allowed")


def sanitize_path(path: str) -> str:
    """Prevent path traversal — collapse and reject any `..` segments."""
    normalized = urllib.parse.unquote(path)
    if ".." in normalized.split("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    return path


HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}

FORWARD_REQUEST_HEADERS = {
    "authorization", "cookie", "user-agent", "accept", "accept-encoding",
    "accept-language", "referer", "origin", "if-modified-since", "if-none-match",
    "range", "content-type", "content-length", "x-emby-token", "x-plex-token",
    "x-mediabrowser-token",
}


def build_upstream_headers(request: Request) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for key, value in request.headers.items():
        lower = key.lower()
        if lower in FORWARD_REQUEST_HEADERS:
            headers[key] = value
    client_ip = request.client.host if request.client else "unknown"
    existing_xff = request.headers.get("x-forwarded-for", "")
    headers["X-Forwarded-For"] = f"{existing_xff}, {client_ip}".strip(", ")
    headers["X-Real-IP"] = client_ip
    headers["X-Forwarded-Proto"] = request.url.scheme
    if CONFIG.media_token:
        headers.setdefault("X-Emby-Token", CONFIG.media_token)
    return headers


def build_response_headers(upstream: httpx.Response) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for key, value in upstream.headers.items():
        if key.lower() in HOP_BY_HOP:
            continue
        headers[key] = value
    return headers


# ═══════════════════════════════════════════════════════════════════════════
# Streaming engine (direct passthrough)
# ═══════════════════════════════════════════════════════════════════════════

class StreamManager:
    """
    Handles direct (non-transcoded) passthrough streaming with full Range
    support, chunked transfer, and backpressure-aware iteration so slow
    clients never cause unbounded memory growth on the proxy.
    """

    def __init__(self, client: httpx.AsyncClient, chunk_size: int) -> None:
        self.client = client
        self.chunk_size = chunk_size

    async def stream(self, method: str, url: str, headers: Dict[str, str],
                      body: Optional[bytes], session_id: str) -> Tuple[httpx.Response, AsyncIterator[bytes]]:
        request = self.client.build_request(method, url, headers=headers, content=body)
        upstream = await self.client.send(request, stream=True)

        async def generator() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.aiter_bytes(self.chunk_size):
                    if chunk:
                        await SESSIONS.update_bytes(session_id, len(chunk))
                        await METRICS.add_bytes(len(chunk))
                        yield chunk
            except (httpx.StreamClosed, httpx.ReadError, asyncio.CancelledError):
                await METRICS.inc_disconnect()
                raise
            finally:
                await upstream.aclose()

        return upstream, generator()


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI application
# ═══════════════════════════════════════════════════════════════════════════

@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global HTTP_CLIENT
    HTTP_CLIENT = build_http_client()
    await HARDWARE.detect()
    log_event(logging.INFO, "proxy_started", media_server=CONFIG.media_server,
              host=CONFIG.host, port=CONFIG.port)
    try:
        yield
    finally:
        log_event(logging.INFO, "proxy_shutting_down")
        await TRANSCODER.shutdown_all()
        if HTTP_CLIENT is not None:
            await HTTP_CLIENT.aclose()
        log_event(logging.INFO, "proxy_shutdown_complete")


app = FastAPI(title="HEVC Transcoding Reverse Proxy", version="1.0.0", lifespan=lifespan)


# ── Monitoring / administrative endpoints ──────────────────────────────────

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "media_server": CONFIG.media_server,
        "active_transcodes": await TRANSCODER.active_count(),
    })


@app.get("/hardware")
async def hardware_endpoint() -> JSONResponse:
    return JSONResponse(await HARDWARE.detect())


@app.get("/sessions")
async def sessions_endpoint() -> JSONResponse:
    return JSONResponse({"sessions": await SESSIONS.list_sessions()})


@app.get("/stats")
async def stats_endpoint() -> JSONResponse:
    return JSONResponse({
        "metrics": await METRICS.snapshot(),
        "cache": await CACHE.stats(),
        "active_transcodes": await TRANSCODER.active_count(),
        "sessions": len(await SESSIONS.list_sessions()),
    })


@app.get("/metrics")
async def metrics_endpoint() -> PlainTextResponse:
    return PlainTextResponse(await METRICS.prometheus_text(), media_type="text/plain; version=0.0.4")


@app.get("/config")
async def config_endpoint() -> JSONResponse:
    safe_config = dataclasses.asdict(CONFIG)
    safe_config.pop("media_token", None)
    safe_config.pop("api_key", None)
    return JSONResponse(safe_config)


# ── Core reverse-proxy / transcoding route ─────────────────────────────────

RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


@app.api_route("/{full_path:path}", methods=["GET", "HEAD", "OPTIONS", "POST"])
async def proxy_route(full_path: str, request: Request) -> Response:
    await METRICS.inc_requests()
    check_api_key(request)
    check_origin(request)
    sanitize_path(full_path)

    client_ip = request.client.host if request.client else "unknown"
    if not await RATE_LIMITER.allow(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    start_time = time.time()

    # Allow an explicit absolute upstream via ?target= so the proxy can act as
    # a general-purpose transcoding gateway in front of any origin (e.g. the
    # external 111movies bcdn hosts) rather than only a fixed MEDIA_SERVER.
    target = request.query_params.get("target")
    if target and urllib.parse.urlparse(target).scheme in ("http", "https"):
        upstream_url = target
    else:
        upstream_url = urllib.parse.urljoin(CONFIG.media_server + "/", full_path)
        if request.url.query:
            upstream_url = f"{upstream_url}?{request.url.query}"

    upstream_headers = build_upstream_headers(request)
    body = await request.body() if request.method == "POST" else None

    if request.method == "OPTIONS":
        return Response(status_code=204)

    HTTP_CLIENT = get_http_client()

    # Only inspect codec for things that look like media, not API/metadata calls.
    looks_like_media = bool(target) or bool(re.search(
        r"\.(mp4|mkv|avi|mov|webm|ts|m3u8|mpd|m4s)(\?|$)", full_path, re.IGNORECASE)) or \
        "videos" in full_path.lower() or "stream" in full_path.lower()

    metadata: Optional[MediaMetadata] = None
    if looks_like_media and request.method in ("GET", "HEAD"):
        try:
            metadata = await INSPECTOR.inspect(upstream_url, upstream_headers)
        except Exception as exc:  # noqa: BLE001 - inspection must never break the proxy
            log_event(logging.WARNING, "inspection_failed", error=str(exc), url=upstream_url)

    should_transcode = bool(metadata and CodecDetector.is_hevc(metadata.codec))

    if not should_transcode:
        return await _handle_passthrough(
            request, upstream_url, upstream_headers, body, client_ip, metadata, start_time,
        )

    return await _handle_transcode(
        request, upstream_url, upstream_headers, client_ip, metadata, start_time,
    )


async def _handle_passthrough(
    request: Request, upstream_url: str, headers: Dict[str, str],
    body: Optional[bytes], client_ip: str, metadata: Optional[MediaMetadata], start_time: float,
) -> Response:
    session = await SESSIONS.create(
        client_ip=client_ip, media_url=upstream_url,
        codec=(metadata.codec if metadata else "n/a"),
        resolution=(f"{metadata.width}x{metadata.height}" if metadata and metadata.width else "n/a"),
        bitrate_kbps=(metadata.bitrate_kbps if metadata else 0.0), mode="direct",
    )
    await METRICS.stream_started()
    stream_manager = StreamManager(HTTP_CLIENT, CONFIG.chunk_size)  # type: ignore[arg-type]

    try:
        upstream, body_iter = await stream_manager.stream(
            request.method, upstream_url, headers, body, session.session_id,
        )
    except httpx.RequestError as exc:
        await METRICS.stream_ended()
        await SESSIONS.remove(session.session_id)
        log_event(logging.ERROR, "upstream_unreachable", url=upstream_url, error=str(exc))
        raise HTTPException(status_code=502, detail="Upstream media server unreachable")

    response_headers = build_response_headers(upstream)
    response_headers.setdefault("Accept-Ranges", "bytes")

    async def cleanup() -> None:
        await METRICS.stream_ended()
        await SESSIONS.remove(session.session_id)
        log_event(
            logging.INFO, "request_complete", session_id=session.session_id,
            client=client_ip, method=request.method, path=str(request.url.path),
            codec=session.codec, mode="direct", status=upstream.status_code,
            latency_ms=round((time.time() - start_time) * 1000, 1),
        )

    if request.method == "HEAD":
        await upstream.aclose()
        await cleanup()
        return Response(status_code=upstream.status_code, headers=response_headers)

    return StreamingResponse(
        body_iter, status_code=upstream.status_code, headers=response_headers,
        background=BackgroundTask(cleanup),
    )


async def _handle_transcode(
    request: Request, upstream_url: str, headers: Dict[str, str],
    client_ip: str, metadata: Optional[MediaMetadata], start_time: float,
) -> Response:
    query_params = dict(request.query_params)
    opts = TranscodeOptions.from_query(query_params)

    # Honor Range requests by translating a byte-ish "seek" hint into a
    # timestamp restart when the client is scrubbing; without duration/bitrate
    # info we conservatively fall back to starting from zero.
    range_header = request.headers.get("range")
    if range_header and metadata and metadata.bitrate_kbps > 0 and metadata.duration_seconds > 0:
        match = RANGE_RE.match(range_header)
        if match:
            start_byte = int(match.group(1))
            total_bytes = (metadata.bitrate_kbps * 1000 / 8) * metadata.duration_seconds
            if total_bytes > 0:
                fraction = min(0.999, start_byte / total_bytes)
                opts.start_time = fraction * metadata.duration_seconds

    resolution = f"{metadata.width}x{metadata.height}" if metadata else "n/a"
    session = await SESSIONS.create(
        client_ip=client_ip, media_url=upstream_url, codec=(metadata.codec if metadata else "hevc"),
        resolution=resolution, bitrate_kbps=(metadata.bitrate_kbps if metadata else 0.0),
        mode="transcode",
    )

    await TRANSCODER.acquire()
    spawn_start = time.time()
    try:
        cmd = await PIPELINE.build_command(opts, upstream_url)
        proc = await TRANSCODER.spawn(cmd)
        first_chunk = await _peek_first_chunk(proc)
        if first_chunk is None and proc.returncode is not None and proc.returncode != 0:
            # Hardware encoder path failed instantly (e.g. no GPU device
            # actually usable despite being compiled in) — fall back to
            # libx264 automatically, per the "always fall back to software"
            # requirement.
            log_event(logging.WARNING, "hardware_transcode_failed_falling_back",
                      pid=proc.pid, exit_code=proc.returncode)
            await METRICS.inc_ffmpeg_failure()
            cmd = await PIPELINE.build_command(opts, upstream_url, force_software=True)
            proc = await TRANSCODER.spawn(cmd)
            first_chunk = await _peek_first_chunk(proc)
    except Exception as exc:  # noqa: BLE001
        TRANSCODER.release()
        await SESSIONS.remove(session.session_id)
        await METRICS.inc_ffmpeg_failure()
        log_event(logging.ERROR, "ffmpeg_spawn_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to start transcoder")

    await SESSIONS.set_pid(session.session_id, proc.pid)
    await METRICS.transcode_started(time.time() - spawn_start)
    await METRICS.stream_started()

    stderr_task = asyncio.create_task(_drain_stderr(proc, session.session_id))

    async def generator() -> AsyncIterator[bytes]:
        assert proc.stdout is not None
        try:
            if first_chunk:
                await SESSIONS.update_bytes(session.session_id, len(first_chunk))
                await METRICS.add_bytes(len(first_chunk))
                yield first_chunk
            while True:
                chunk = await proc.stdout.read(CONFIG.chunk_size)
                if not chunk:
                    break
                await SESSIONS.update_bytes(session.session_id, len(chunk))
                await METRICS.add_bytes(len(chunk))
                yield chunk
        except asyncio.CancelledError:
            await METRICS.inc_disconnect()
            raise
        finally:
            await _cleanup_transcode(proc, stderr_task, session, request, start_time)

    media_type = "video/mp2t" if opts.output_format == "mpegts" else "video/mp4"
    response_headers = {"Accept-Ranges": "none", "Cache-Control": "no-cache"}
    return StreamingResponse(generator(), media_type=media_type, headers=response_headers)


async def _peek_first_chunk(proc: asyncio.subprocess.Process, timeout: float = 3.0) -> Optional[bytes]:
    """
    Attempt to read the first chunk of ffmpeg's stdout within a short window.
    Returns None if ffmpeg produced nothing (used to detect an immediate
    hardware-encoder failure so we can fall back to software transparently).
    """
    assert proc.stdout is not None
    try:
        chunk = await asyncio.wait_for(proc.stdout.read(CONFIG.chunk_size), timeout=timeout)
        if not chunk:
            # stdout closed with nothing written — make sure returncode is
            # populated so the caller can reliably detect a failed launch.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=1.0)
            return None
        return chunk
    except asyncio.TimeoutError:
        # Still running and just hasn't produced output yet (e.g. slow
        # source) — treat as healthy rather than a failure.
        return b""


async def _drain_stderr(proc: asyncio.subprocess.Process, session_id: str) -> None:
    assert proc.stderr is not None
    try:
        async for raw_line in proc.stderr:
            line = raw_line.decode(errors="ignore").strip()
            if not line:
                continue
            progress = TranscodeManager.parse_progress_line(line)
            if "fps" in progress:
                await SESSIONS.set_fps(session_id, progress["fps"])
                await METRICS.record_fps(progress["fps"])
            if "bitrate_kbps" in progress:
                await METRICS.record_bitrate(progress["bitrate_kbps"])
            if re.search(r"error|failed", line, re.IGNORECASE):
                log_event(logging.WARNING, "ffmpeg_stderr", session_id=session_id, line=line)
    except (asyncio.CancelledError, ValueError):
        pass


async def _cleanup_transcode(
    proc: asyncio.subprocess.Process, stderr_task: asyncio.Task, session: Session,
    request: Request, start_time: float,
) -> None:
    return_code = await TRANSCODER.terminate(proc)
    stderr_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await stderr_task
    await METRICS.transcode_ended()
    await METRICS.stream_ended()
    TRANSCODER.release()
    if return_code not in (0, None, -15, -9):
        await METRICS.inc_ffmpeg_failure()
    log_event(
        logging.INFO, "transcode_complete", session_id=session.session_id,
        client=session.client_ip, method=request.method, path=str(request.url.path),
        codec=session.codec, mode="transcode", ffmpeg_pid=proc.pid, exit_code=return_code,
        bytes_sent=session.bytes_sent, latency_ms=round((time.time() - start_time) * 1000, 1),
    )
    await SESSIONS.remove(session.session_id)


# ═══════════════════════════════════════════════════════════════════════════
# Graceful shutdown wiring (SIGTERM/SIGINT) + entrypoint
# ═══════════════════════════════════════════════════════════════════════════

def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    def _handler(sig_name: str) -> None:
        log_event(logging.INFO, "signal_received", signal=sig_name)

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, ValueError):
            loop.add_signal_handler(sig, _handler, sig.name)


def main() -> None:
    if uvicorn is None:
        print("uvicorn is required to run this server: pip install uvicorn[standard]",
              file=sys.stderr)
        sys.exit(1)

    log_event(
        logging.INFO, "proxy_configured", media_server=CONFIG.media_server,
        max_transcodes=CONFIG.max_transcodes, gpu_priority=CONFIG.gpu_order(),
    )

    uvicorn.run(
        "proxy:app" if __name__ == "__main__" else app,
        host=CONFIG.host,
        port=CONFIG.port,
        log_level=CONFIG.log_level.lower(),
        loop="asyncio",
        http="auto",
        timeout_graceful_shutdown=15,
    )


if __name__ == "__main__":
    main()