"""Official-domain knowledge: the gov.in rule, an operator allowlist, and Wikidata P856.

gov.in eligibility (government bodies only): https://registry.gov.in/registration_guidelines.php
Official bodies also use other domains (RBI: rbi.org.in, IRCTC: irctc.co.in), so
"not gov.in" is never evidence of fake on its own.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import tldextract

from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient, json_or_error
from satyapan.security.ssrf import normalise_url, valid_hostname

OFFICIAL_SUFFIXES = {"gov.in", "nic.in"}
EXTRACT = tldextract.TLDExtract(suffix_list_urls=())   # bundled public-suffix list, no network
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
QUERY = """SELECT DISTINCT ?item ?site WHERE {
  VALUES ?name { "%s"@en }
  { ?item rdfs:label ?name } UNION { ?item skos:altLabel ?name }
  ?item wdt:P856 ?site .
} LIMIT 10"""


def domain_info(url_or_host: str) -> dict:
    """Host facts for a link, parsed the way a browser parses it.

    valid_host is False for anything that is not a DNS hostname (percent signs, slashes,
    spaces). Such hosts are never official and are never sent to RDAP or other services.
    """
    raw = normalise_url(url_or_host)
    try:
        parts = urlsplit(raw if "://" in raw else f"http://{raw}")
        host = (parts.hostname or "").lower().rstrip(".")
        userinfo = parts.username or ""
    except ValueError:
        host, userinfo = "", ""
    valid = valid_hostname(host)
    ext = EXTRACT(host) if host else None
    if valid and ext and ext.domain and ext.suffix:
        registered, suffix, subdomain = f"{ext.domain}.{ext.suffix}", ext.suffix, ext.subdomain
    else:
        registered, suffix, subdomain = host, (ext.suffix if ext else ""), (ext.subdomain if ext else "")
    return {"host": host, "registered": registered, "suffix": suffix, "subdomain": subdomain,
            "official_suffix": valid and suffix in OFFICIAL_SUFFIXES, "valid_host": valid, "userinfo": userinfo}


def load_allowlist(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {ln.strip().lower() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")}


def wikidata_official_sites(client: ApiClient, name: str) -> dict:
    safe = name.replace("\\", "\\\\").replace('"', '\\"')
    resp, ms = client.request("wikidata", "GET", WIKIDATA_SPARQL,
                              params={"query": QUERY % safe, "format": "json"},
                              headers={"Accept": "application/sparql-results+json"})
    if resp.status_code != 200:
        raise ToolError(ToolStatus.SERVICE_ERROR, resp.text[:200], resp.status_code)
    rows = json_or_error(resp, "wikidata").get("results", {}).get("bindings", [])
    sites = sorted({r["site"]["value"] for r in rows if "site" in r})
    return {"name": name, "sites": sites, "registered": sorted({domain_info(s)["registered"] for s in sites}),
            "items": sorted({r["item"]["value"] for r in rows if "item" in r}), "ms": ms}
