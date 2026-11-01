"""C2PA Content Credentials (module 5).

Library: https://github.com/contentauth/c2pa-python (pip install c2pa-python, Python 3.10+)
present  -> manifest found. Report signer, validation state, declared AI use.
none     -> no manifest. PROVES NOTHING: forwarding and re-encoding strip it (tested).
"""
from __future__ import annotations

import json
from pathlib import Path

import c2pa

AI_SOURCE_TYPES = ("trainedAlgorithmicMedia", "compositeWithTrainedAlgorithmicMedia")


def inspect(path: Path) -> dict:
    try:
        with c2pa.Reader(str(path)) as reader:
            data = json.loads(reader.json())
    except c2pa.C2paError as exc:
        name, msg = type(exc).__name__, str(exc)
        if "ManifestNotFound" in name or "no JUMBF" in msg:
            return {"status": "none"}
        if "RemoteManifest" in name or msg.startswith("Remote"):
            return {"status": "remote_unreachable", "detail": msg[:160]}
        if "NotSupported" in name:
            return {"status": "unsupported_format"}
        return {"status": "error", "detail": f"{name}: {msg[:160]}"}
    manifest = data.get("manifests", {}).get(data.get("active_manifest"), {})
    sources = [a.get("digitalSourceType") for asr in manifest.get("assertions", [])
               if str(asr.get("label", "")).startswith("c2pa.actions")
               for a in (asr.get("data") or {}).get("actions", []) if a.get("digitalSourceType")]
    sig = manifest.get("signature_info") or {}
    return {"status": "present", "validation_state": data.get("validation_state"),
            "validation_codes": [v.get("code") for v in data.get("validation_status", [])],
            "issuer": sig.get("issuer"), "signed_at": sig.get("time"),
            "claim_generator": manifest.get("claim_generator") or str(manifest.get("claim_generator_info")),
            "digital_source_types": sources,
            "ai_declared": any(t in s for s in sources for t in AI_SOURCE_TYPES)}
