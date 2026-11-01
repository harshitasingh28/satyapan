"""PIB ingestion after the live MacBook run of 31 Oct 2026, where PIB answered HTTP 403 to all feeds.

Offline. The RSS below is a FIXTURE, not a real PIB feed.
"""
import subprocess
import sys

import httpx
import pytest

from conftest import ROOT
from satyapan.errors import ToolError, ToolStatus
from satyapan.http import ApiClient
from satyapan.sources import pib

RSS = b"""<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>FIXTURE</title>
<item><title>FIXTURE Cabinet approves scheme</title><link>https://pib.gov.in/PressReleasePage.aspx?PRID=999001</link>
<description>fixture</description></item></channel></rss>"""


def test_403_from_pib_is_blocked_not_auth_required():
    client = ApiClient(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="Access Denied")))
    with pytest.raises(ToolError) as exc:
        pib.fetch_feed(client, "releases_en_documented")
    assert exc.value.status == ToolStatus.BLOCKED and "--from-file" in exc.value.message


def test_saved_feed_and_manual_release_are_imported(tmp_path):
    f = tmp_path / "pib.xml"
    f.write_bytes(RSS)
    # The script loads the developer's .env. Empty values here win over it (python-dotenv never overrides a
    # variable that is already set), so the FIXTURE releases can never reach a real MongoDB database.
    env = {"SATYAPAN_DATA_DIR": str(tmp_path / "data"), "PATH": "/usr/bin:/bin", "MONGODB_URI": "", "MONGODB_DB": ""}
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "ingest_pib.py"), *a],
                                    capture_output=True, text=True, env=env)
    assert "new 1" in run("--from-file", str(f)).stdout
    assert "added 1" in run("--add", "--title", "FIXTURE manual", "--link",
                            "https://pib.gov.in/PressReleasePage.aspx?PRID=999002").stdout
    bad = run("--add", "--title", "x", "--link", "https://pib.gov.in.evil.top/x")
    assert bad.returncode != 0 and "refused" in bad.stderr
    items = pib.PibStore(tmp_path / "data" / "pib_releases.jsonl").load()
    assert {i["prid"] for i in items} == {999001, 999002}
