"""RDAP domain registration data via the IANA bootstrap.

Bootstrap: https://data.iana.org/rdap/dns.json  (.in -> https://rdap.nixiregistry.in/rdap/, .co not listed)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from satyapan.config import get_settings
from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient, json_or_error
from satyapan.security.ssrf import valid_hostname

BOOTSTRAP = "https://data.iana.org/rdap/dns.json"


def _bootstrap(client: ApiClient) -> dict:
    cache: Path = get_settings().data_dir / "rdap_dns.json"
    if not cache.exists() or time.time() - cache.stat().st_mtime > 86400:
        resp, _ = client.request("rdap_bootstrap", "GET", BOOTSTRAP)
        if resp.status_code != 200:
            raise ToolError(ToolStatus.SERVICE_ERROR, f"bootstrap HTTP {resp.status_code}", resp.status_code)
        cache.write_bytes(resp.content)
    return json.loads(cache.read_text(encoding="utf-8"))


def server_for(client: ApiClient, tld: str) -> str | None:
    for tlds, servers in _bootstrap(client).get("services", []):
        if tld in tlds and servers:
            base = next((s for s in servers if s.startswith("https://")), None)
            if base:
                client.allow_host(urlsplit(base).hostname or "")
                return base if base.endswith("/") else base + "/"
    return None


def lookup(client: ApiClient, registered_domain: str) -> dict:
    # Defence in depth: the domain becomes part of a request path, so only DNS names go out.
    if not valid_hostname(registered_domain):
        raise ToolError(ToolStatus.INPUT_ERROR, "not a valid domain name, RDAP not queried")
    tld = registered_domain.rsplit(".", 1)[-1].lower()
    base = server_for(client, tld)
    if base is None:
        return {"status": "no_rdap_server", "tld": tld}
    resp, ms = client.request("rdap_domain", "GET", f"{base}domain/{registered_domain}",
                              headers={"Accept": "application/rdap+json"})
    if resp.status_code == 404:
        return {"status": "not_found", "ms": ms}
    if resp.status_code != 200:
        raise ToolError(ToolStatus.SERVICE_ERROR, f"RDAP HTTP {resp.status_code}", resp.status_code)
    data = json_or_error(resp, "rdap_domain")
    registered = next((e.get("eventDate") for e in data.get("events", [])
                       if e.get("eventAction") == "registration"), None)
    age = None
    if registered:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(registered.replace("Z", "+00:00"))).days
    return {"status": "found", "registered": registered, "age_days": age, "ms": ms,
            "fields": sorted(data.keys())}
