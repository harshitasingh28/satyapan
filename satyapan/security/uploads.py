"""Upload validation: trust the bytes, not the file name.

Checks: size limit per kind, magic-byte sniffing, Pillow decode with a pixel
limit (decompression bombs), ffprobe with a timeout for audio/video, duration
limit, and a sanitised copy (re-encoded, metadata stripped) for any third party.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from satyapan.config import Settings, get_settings

MP4_BRANDS_VIDEO = {b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"qt  ", b"3gp4", b"3gp5", b"dash", b"M4V "}
MP4_BRANDS_AUDIO = {b"M4A ", b"M4B "}
DURATION_TOLERANCE_S = 0.5


def sniff(head: bytes) -> tuple[str, str] | None:
    """Return (kind, mime) from the first bytes, or None if unsupported."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio", "audio/wav"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in MP4_BRANDS_AUDIO:
            return "audio", "audio/mp4"
        if brand in MP4_BRANDS_VIDEO:
            return "video", "video/mp4"
        return None
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video", "video/webm"
    if head.startswith(b"OggS"):
        return "audio", "audio/ogg"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio", "audio/mpeg"
    return None


@dataclass
class MediaInfo:
    ok: bool
    kind: str = ""
    mime: str = ""
    size_bytes: int = 0
    sha256: str = ""
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def ffprobe(path: Path, timeout: float = 10.0) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
                         capture_output=True, text=True, timeout=timeout, check=False)
    if out.returncode != 0:
        raise ValueError(f"ffprobe rejected the file: {out.stderr.strip()[:160]}")
    return json.loads(out.stdout or "{}")


def validate_upload(path: Path, declared_name: str = "", settings: Settings | None = None) -> MediaInfo:
    s = settings or get_settings()
    info = MediaInfo(ok=False, size_bytes=path.stat().st_size)
    with path.open("rb") as fh:
        head = fh.read(32)
    sniffed = sniff(head)
    if sniffed is None:
        info.errors.append("unsupported or unrecognised file type")
        return info
    info.kind, info.mime = sniffed
    limit_mb = {"image": s.max_image_mb, "video": s.max_video_mb, "audio": s.max_audio_mb}[info.kind]
    if info.size_bytes > limit_mb * 1024 * 1024:
        info.errors.append(f"{info.kind} larger than {limit_mb} MB")
        return info
    ext = Path(declared_name).suffix.lower().lstrip(".")
    if ext and ext not in info.mime and not (ext in ("jpg", "jpeg") and info.mime == "image/jpeg") \
            and not (ext in ("mov", "m4v") and info.mime == "video/mp4"):
        info.warnings.append(f"extension .{ext} does not match content {info.mime}, content wins")

    if info.kind == "image":
        # Pillow only RAISES above 2x MAX_IMAGE_PIXELS (it warns in between), so the limit is
        # also checked explicitly from the header, before any pixel is decoded.
        Image.MAX_IMAGE_PIXELS = s.max_image_pixels
        try:
            with Image.open(path) as im:
                if im.size[0] * im.size[1] > s.max_image_pixels:
                    info.width, info.height = im.size
                    info.errors.append(f"image exceeds the pixel limit ({im.size[0]}x{im.size[1]} > "
                                       f"{s.max_image_pixels:,} pixels)")
                    return info
                im.verify()
            with Image.open(path) as im:
                info.width, info.height = im.size
                im.load()
        except Image.DecompressionBombError:
            info.errors.append("image exceeds the pixel limit")
            return info
        except Exception as exc:  # Pillow raises many types for corrupt files
            info.errors.append(f"image failed to decode: {type(exc).__name__}")
            return info
    else:
        try:
            probe = ffprobe(path)
        except (ValueError, subprocess.TimeoutExpired) as exc:
            info.errors.append(str(exc))
            return info
        streams = probe.get("streams", [])
        info.duration_s = float(probe.get("format", {}).get("duration") or 0)
        if info.kind == "video":
            video = next((st for st in streams if st.get("codec_type") == "video"), None)
            if not video:
                info.errors.append("no video stream")
                return info
            info.width, info.height = video.get("width"), video.get("height")
        if info.kind == "audio" and not any(st.get("codec_type") == "audio" for st in streams):
            info.errors.append("no audio stream")
            return info
        if info.duration_s > s.max_media_seconds + DURATION_TOLERANCE_S:     # containers round durations
            info.errors.append(f"longer than {s.max_media_seconds} s")
            return info

    info.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    info.ok = True
    return info


def sanitized_image_copy(path: Path, out_dir: Path, max_side: int = 2048) -> Path:
    """Re-encode without EXIF/GPS/XMP before any third-party upload."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{path.stem}_clean.jpg"
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        im.save(out, "JPEG", quality=90)
    return out
