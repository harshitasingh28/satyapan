"""Image index, C2PA, video keyframes, audio fingerprints and OCR, on real public media."""
import io
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from conftest import MEDIA, need
from satyapan.media import c2pa_inspect
from satyapan.media.audio import AudioIndex, voice_authenticity
from satyapan.media.image_index import ImageIndex
from satyapan.media.video import keyframes
from satyapan.ocr import available_languages, ocr_image


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def screenshot_of(im: Image.Image) -> Image.Image:
    """A phone-screenshot-like frame: status bar, chat bubble padding, caption."""
    w, h = im.size
    canvas = Image.new("RGB", (w + 80, h + 320), (236, 229, 221))
    canvas.paste(im, (40, 160))
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, w + 80, 70], fill=(7, 94, 84))
    d.text((50, h + 190), "Forwarded many times. Share with everyone!", fill=(0, 0, 0))
    return canvas


def test_image_index_real_photos(images):
    idx = ImageIndex()
    for p in images:
        idx.add(p.stem, p, source_url=f"https://factcheck.example/{p.stem}")
    # A natural photo. Low-texture images (cell.png) fail the off-centre crop: see
    # eval/provenance_benchmark.py, which measures every image and is the real result.
    target = next(p for p in images if p.stem == "coffee")
    im = Image.open(target).convert("RGB")
    w, h = im.size
    buf = io.BytesIO()
    im.resize((w // 2, h // 2)).save(buf, "JPEG", quality=35)
    variants = {
        "resize_jpeg35": Image.open(io.BytesIO(buf.getvalue())),
        "offcentre_crop60": im.crop((0, 0, int(w * 0.6), int(h * 0.6))),
        "screenshot": screenshot_of(im),
        "rotate4": im.rotate(4, expand=True, fillcolor=(255, 255, 255)),
    }
    for name, v in variants.items():
        hits = idx.query(v)
        assert hits and hits[0]["id"] == target.stem, f"{name} did not match"
    other = Image.open(images[7]).convert("RGB")
    assert all(h["id"] == images[7].stem for h in idx.query(other)), "unrelated image matched"


def test_index_save_load(images, tmp_dir):
    idx = ImageIndex()
    for p in images[:5]:
        idx.add(p.stem, p)
    idx.save(tmp_dir / "ix")
    again = ImageIndex.load(tmp_dir / "ix")
    assert again.query(images[2])[0]["id"] == images[2].stem


def test_c2pa_present_none_and_stripped(tmp_dir):
    signed, plain = need(MEDIA / "c2pa" / "C.jpg"), need(MEDIA / "c2pa" / "A.jpg")
    r = c2pa_inspect.inspect(signed)
    assert r["status"] == "present" and r["validation_state"] and r["issuer"] == "C2PA Test Signing Cert"
    assert c2pa_inspect.inspect(plain)["status"] == "none"
    stripped = tmp_dir / "C_reencoded.jpg"
    Image.open(signed).convert("RGB").save(stripped, "JPEG", quality=85)
    assert c2pa_inspect.inspect(stripped)["status"] == "none"     # forwarding-style re-encode removes it


def test_video_keyframes_find_recycled_frames(images, tmp_dir):
    slides = tmp_dir / "slides"
    slides.mkdir()
    for i, p in enumerate(images[:5]):
        Image.open(p).convert("RGB").resize((640, 480)).save(slides / f"s{i}.png")
    clip = tmp_dir / "clip.mp4"
    ff("-framerate", "1/3", "-i", str(slides / "s%d.png"), "-vf", "fps=25,format=yuv420p", "-c:v", "libx264",
       "-preset", "veryfast", str(clip))
    reshared = tmp_dir / "reshared.mp4"     # cropped and re-encoded at low bitrate, like a re-upload
    ff("-i", str(clip), "-vf", "crop=iw*0.9:ih*0.9", "-c:v", "libx264", "-preset", "veryfast", "-b:v", "150k",
       str(reshared))
    res = keyframes(reshared, tmp_dir / "frames")
    assert len(res["frames"]) >= 4
    idx = ImageIndex()
    for p in images[:5]:
        idx.add(p.stem, p)
    matched = {h[0]["id"] for f in res["frames"] if (h := idx.query(f))}
    assert len(matched) >= 4


def test_audio_fingerprint_real_speech(tmp_dir):
    a, b, music = (need(MEDIA / "audio" / n) for n in ("speech_a.ogg", "speech_b.ogg", "music.ogg"))
    idx = AudioIndex()
    idx.add("A", a)
    idx.add("B", b)
    ff("-ss", "3", "-t", "6", "-i", str(a), "-c:a", "libopus", "-b:a", "16k", str(tmp_dir / "a.ogg"))
    ff("-ss", "2", "-t", "5", "-i", str(b), "-c:a", "libmp3lame", "-b:a", "32k", str(tmp_dir / "b.mp3"))
    ff("-ss", "3", "-t", "6", "-i", str(a), "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.05",
       "-filter_complex", "amix=inputs=2:duration=first", str(tmp_dir / "a_noise.wav"))
    ff("-ss", "10", "-t", "6", "-i", str(music), str(tmp_dir / "music.wav"))
    ra = idx.query(tmp_dir / "a.ogg")[0]
    assert ra["id"] == "A" and ra["match"] and abs(ra["offset_s"] - 3.0) < 0.2
    rb = idx.query(tmp_dir / "b.mp3")[0]
    assert rb["id"] == "B" and rb["match"] and abs(rb["offset_s"] - 2.0) < 0.2
    rn = idx.query(tmp_dir / "a_noise.wav")[0]
    assert rn["id"] == "A" and rn["match"]
    assert not any(r["match"] for r in idx.query(tmp_dir / "music.wav"))


def test_voice_authenticity_defaults_to_unverified():
    r = voice_authenticity(Path("unused.wav"))
    assert r["status"] == "UNVERIFIED" and "does not judge" in r["limitation"]


def test_ocr_rendered_hindi_english(tmp_dir):
    """Mechanics test on RENDERED text, not a real screenshot. Real accuracy needs the dataset."""
    font = need(MEDIA / "fonts" / "NotoSansDevanagari.ttf")
    if not {"hin", "eng"} <= available_languages():
        pytest.skip("tesseract hin/eng data not available")
    img = Image.new("RGB", (1400, 260), "white")
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(str(font), 44)
    d.text((30, 30), "सरकार सभी किसानों को ₹10,000 देगी", font=f, fill="black")
    d.text((30, 140), "Apply now at pmkisan-gov.top", font=f, fill="black")
    path = tmp_dir / "msg.png"
    img.save(path)
    res = ocr_image(path, "eng+hin")
    assert res["ok"] and "pmkisan-gov.top" in res["text"].replace(" ", "")
    assert "सरकार" in res["text"]
