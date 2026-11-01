"""SSRF checks, upload validation, redaction, allowlist, rate limits.

The guarded_fetch tests use a fake resolver and a mock HTTP transport. They test
the redirect and DNS-rebinding LOGIC, not a live fetch.
"""
import io

import httpx
import pytest
from PIL import Image

from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient
from satyapan.logging_setup import redact
from satyapan.security.ratelimit import DailyBudget, TokenBucket
from satyapan.security.ssrf import guarded_fetch, validate_url
from satyapan.security.uploads import sanitized_image_copy, sniff, validate_upload


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "gopher://example.com", "http://127.0.0.1/", "http://2130706433/", "http://0x7f000001/",
    "http://127.1/", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.5/", "http://192.168.1.1/", "http://100.64.1.1/", "http://localhost:80/", "http://router.local/",
    "http://db.internal/", "http://user:pass@example.com/", "http://example.com:8080/", "http://0.0.0.0/",
])
def test_rejects_unsafe_urls(url):
    assert not validate_url(url).ok


def test_accepts_public_urls():
    assert validate_url("https://example.com/path?q=1").ok
    assert validate_url("http://8.8.8.8/").ok


def test_dns_rebinding_is_caught_by_resolution():
    check = validate_url("https://evil.example/", resolve=True, resolver=lambda h: ["93.184.216.34", "10.0.0.7"])
    assert not check.ok and "10.0.0.7" in check.reason


def test_guarded_fetch_refuses_redirect_to_private_address():
    seen = []

    def handler(request: httpx.Request):
        seen.append((str(request.url), request.headers.get("host"), request.extensions.get("sni_hostname")))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    res = guarded_fetch("https://short.example/abc", resolver=lambda h: ["93.184.216.34"],
                        transport=httpx.MockTransport(handler))
    assert not res.ok and "not public" in res.reason
    url, host, sni = seen[0]
    assert url.startswith("https://93.184.216.34/") and host == "short.example" and sni == "short.example"


def test_sniff_and_upload_validation(tmp_dir, images):
    jpg = tmp_dir / "photo.jpg"
    Image.open(images[0]).convert("RGB").save(jpg, "JPEG")
    assert validate_upload(jpg, "photo.jpg").ok
    png_named_jpg = tmp_dir / "x.jpg"
    Image.open(images[0]).convert("RGB").save(png_named_jpg, "PNG")
    info = validate_upload(png_named_jpg, "x.jpg")
    assert info.ok and info.mime == "image/png" and info.warnings
    fake = tmp_dir / "evil.jpg"
    fake.write_bytes(b"#!/bin/sh\necho owned\n")
    assert not validate_upload(fake, "evil.jpg").ok
    truncated = tmp_dir / "cut.jpg"
    truncated.write_bytes(jpg.read_bytes()[:2000])
    assert not validate_upload(truncated, "cut.jpg").ok
    assert sniff(b"\x00\x00\x00\x18ftypmp42") == ("video", "video/mp4")


def test_decompression_bomb_rejected(tmp_dir):
    bomb = tmp_dir / "bomb.png"
    Image.new("1", (9000, 9000)).save(bomb, "PNG")          # 81 MP, a few KB on disk
    info = validate_upload(bomb, "bomb.png")
    assert not info.ok and "pixel limit" in info.errors[0]


def test_sanitized_copy_strips_metadata(tmp_dir, images):
    src = tmp_dir / "gps.jpg"
    im = Image.open(images[0]).convert("RGB")
    exif = Image.Exif()
    exif[0x8825] = {2: (28.0, 36.0, 0.0), 4: (77.0, 12.0, 0.0)}   # GPSInfo
    exif[0x010F] = "PhoneMaker"
    im.save(src, "JPEG", exif=exif)
    assert Image.open(src).getexif()
    clean = sanitized_image_copy(src, tmp_dir / "clean")
    assert not Image.open(clean).getexif()


def test_redaction():
    line = 'GET https://x.googleapis.com/v1?query=a&key=AIzaSECRET123 headers {"API-Key": "abc-123", "Authorization": "Bearer tok"}'
    out = redact(line)
    assert "AIzaSECRET123" not in out and "abc-123" not in out and "tok\"" not in out


def test_allowlist_blocks_other_hosts():
    client = ApiClient()
    with pytest.raises(ToolError) as e:
        client.request("t", "GET", "https://evil.example.com/steal")
    assert e.value.status == ToolStatus.BLOCKED
    with pytest.raises(ToolError):
        client.request("t", "GET", "http://factchecktools.googleapis.com/")   # plain http refused


@pytest.mark.parametrize("code,status", [(429, ToolStatus.RATE_LIMITED), (403, ToolStatus.AUTH_REQUIRED),
                                         (503, ToolStatus.SERVICE_ERROR)])
def test_status_mapping(code, status):
    client = ApiClient(transport=httpx.MockTransport(lambda r: httpx.Response(code, text="x")))
    with pytest.raises(ToolError) as e:
        client.request("t", "GET", "https://urlscan.io/api/v1/quotas", retries=0)
    assert e.value.status == status


def test_rate_limit_and_budget(tmp_dir):
    b = TokenBucket(per_minute=3)
    assert [b.allow("ip") for _ in range(4)] == [True, True, True, False]
    budget = DailyBudget(tmp_dir / "b.json", {"sightengine_genai": 2})
    assert [budget.take("sightengine_genai") for _ in range(3)] == [True, True, False]
