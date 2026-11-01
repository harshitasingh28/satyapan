"""URL safety for user-submitted links.

Satyapan's backend does not fetch user URLs (see satyapan/http.py). These checks
still run on every submitted link, for two reasons:
  1. A link that points to a private or local address is rejected before it is
     sent to any third party (urlscan would otherwise be asked to scan it).
  2. guarded_fetch() exists for one optional feature, expanding URL shorteners.
     It is OFF by default (SATYAPAN_ENABLE_GUARDED_FETCH=1 to enable). It
     resolves DNS once, checks every address, connects to the checked address
     (defeating DNS rebinding) and re-validates every redirect hop.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import unicodedata
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".arpa")
EXTRA_BLOCKED_NETS = [ipaddress.ip_network(n) for n in
                      ("100.64.0.0/10", "192.0.0.0/24", "198.18.0.0/15", "0.0.0.0/8")]

LDH_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")

Resolver = Callable[[str], list[str]]


def normalise_url(url: str) -> str:
    """Parse links the way a browser does.

    Browsers (WHATWG URL standard) treat a backslash like a slash in http(s) URLs.
    Python's urlsplit does not, so "http://x.com\\@pib.gov.in/" looks like pib.gov.in
    to Python but opens x.com in a browser. Normalising first removes that gap.
    """
    url = url.strip()
    if url.lower().startswith(("http://", "https://")) or "://" not in url:
        url = url.replace("\\", "/")
    # Browsers also apply IDNA mapping (UTS 46): invisible format characters such as U+200B are
    # dropped and full-width letters and dots become ASCII. Without this, "pmki<ZWSP>san.gov.in.x.top"
    # or "uidai．gov．in．x．top" hid an official name from every check (independent tester, K19).
    url = "".join(ch for ch in url if unicodedata.category(ch) != "Cf")
    return unicodedata.normalize("NFKC", url).replace("\u3002", ".")


def valid_hostname(host: str) -> bool:
    """Strict DNS hostname check (letters, digits, hyphens per label, after IDNA encoding)."""
    host = host.rstrip(".").lower()
    if not host or len(host) > 253:
        return False
    # letters, marks and digits of any script, plus "-" and ".". Punctuation such as the
    # Devanagari danda (।) can never be part of a host name.
    if any(ch not in "-." and unicodedata.category(ch)[0] not in "LMN" for ch in host):
        return False
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    labels = ascii_host.split(".")
    return len(labels) >= 2 and all(LDH_LABEL.match(label) for label in labels)


def system_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def literal_ip(host: str):
    """Parse IP literals, including tricks like 2130706433, 0x7f000001 and 127.1."""
    host = host.strip("[]")
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if host and all(c in "0123456789abcdefxABCDEFX." for c in host):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            return None
    return None


def is_public(ip) -> bool:
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not ip.is_global or ip.is_multicast:
        return False
    return not any(ip in net for net in EXTRA_BLOCKED_NETS if net.version == ip.version)


@dataclass
class UrlCheck:
    ok: bool
    reason: str
    url: str
    host: str = ""
    addresses: list[str] = field(default_factory=list)


def validate_url(url: str, resolve: bool = False, resolver: Resolver = system_resolver) -> UrlCheck:
    try:
        parts = urlsplit(normalise_url(url))
        port = parts.port
    except ValueError as exc:
        return UrlCheck(False, f"unparseable URL: {exc}", url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        return UrlCheck(False, f"scheme {parts.scheme or '(none)'} not allowed", url)
    if parts.username or parts.password:
        return UrlCheck(False, "credentials inside URL are not allowed", url)
    if port not in ALLOWED_PORTS:
        return UrlCheck(False, f"port {port} not allowed", url)
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        return UrlCheck(False, "missing host", url)
    if host == "localhost" or host.endswith(BLOCKED_SUFFIXES):
        return UrlCheck(False, f"host {host} is local", url, host)
    ip = literal_ip(host)
    if ip is not None:
        if not is_public(ip):
            return UrlCheck(False, f"address {ip} is not public", url, host, [str(ip)])
        return UrlCheck(True, "public IP literal", url, host, [str(ip)])
    if not valid_hostname(host):
        return UrlCheck(False, "host has characters that are not allowed in DNS names", url, host)
    if not resolve:
        return UrlCheck(True, "syntax ok (not resolved)", url, host)
    try:
        addrs = resolver(host)
    except (socket.gaierror, OSError) as exc:
        return UrlCheck(False, f"DNS failed: {exc}", url, host)
    if not addrs:
        return UrlCheck(False, "DNS returned no addresses", url, host)
    bad = [a for a in addrs if not is_public(ipaddress.ip_address(a))]
    if bad:
        return UrlCheck(False, f"resolves to non-public address {bad[0]}", url, host, addrs)
    return UrlCheck(True, "resolved to public addresses", url, host, addrs)


@dataclass
class FetchResult:
    ok: bool
    final_url: str
    hops: list[dict]
    reason: str = ""


def guarded_fetch(url: str, *, max_redirects: int = 3, timeout: float = 5.0,
                  resolver: Resolver = system_resolver,
                  transport: httpx.BaseTransport | None = None) -> FetchResult:
    """Follow redirects safely to learn where a link ends up. Never reads more than headers."""
    if os.getenv("SATYAPAN_ENABLE_GUARDED_FETCH") != "1" and transport is None:
        return FetchResult(False, url, [], "guarded fetch disabled (use urlscan instead)")
    hops: list[dict] = []
    current = url
    with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as client:
        for _ in range(max_redirects + 1):
            check = validate_url(current, resolve=True, resolver=resolver)
            hops.append({"url": current, "ok": check.ok, "reason": check.reason, "addresses": check.addresses})
            if not check.ok:
                return FetchResult(False, current, hops, check.reason)
            parts = urlsplit(current)
            ip = check.addresses[0]
            ip_host = f"[{ip}]" if ":" in ip else ip
            netloc = ip_host if parts.port is None else f"{ip_host}:{parts.port}"
            pinned = parts._replace(netloc=netloc).geturl()
            try:
                with client.stream("GET", pinned, headers={"Host": check.host},
                                   extensions={"sni_hostname": check.host}) as resp:
                    status, location = resp.status_code, resp.headers.get("location")
            except httpx.HTTPError as exc:
                return FetchResult(False, current, hops, f"network: {exc}")
            hops[-1]["status"] = status
            if status in (301, 302, 303, 307, 308) and location:
                current = urljoin(current, location)
                continue
            return FetchResult(True, current, hops)
    return FetchResult(False, current, hops, "too many redirects")
