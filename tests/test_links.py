from satyapan.links.urlinfo import analyse_url

OFFICIAL = {"pmkisan.gov.in", "uidai.gov.in", "rbi.org.in", "pib.gov.in"}


def test_official_and_allowlisted():
    assert analyse_url("https://pmkisan.gov.in/", OFFICIAL)["official"]
    a = analyse_url("https://www.rbi.org.in/Scripts/x.aspx", OFFICIAL)
    assert a["official"] and a["allowlisted"] and not a["official_suffix"]


def test_impersonation_patterns():
    a = analyse_url("http://pmkisan-gov.top/apply", OFFICIAL)
    assert not a["official"] and "gov_token_outside_gov_in" in a["flags"] and "not_https" in a["flags"]
    b = analyse_url("https://uidai.gov.in.verify-aadhaar.xyz/kyc", OFFICIAL)
    assert b["registered"] == "verify-aadhaar.xyz" and "official_name_inside_other_domain" in b["flags"]
    c = analyse_url("https://pmkisam.in/", OFFICIAL)
    assert "lookalike_of_official_domain" in c["flags"]


def test_punycode_homoglyph():
    host = "pіb.in"      # Cyrillic і
    puny = host.encode("idna").decode()
    a = analyse_url(f"https://{puny}/", OFFICIAL)
    assert "punycode_host" in a["flags"] and "lookalike_of_official_domain" in a["flags"]


def test_shortener_and_private_target():
    assert "url_shortener" in analyse_url("https://bit.ly/abc", OFFICIAL)["flags"]
    assert "unsafe_or_local_target" in analyse_url("http://192.168.0.1/login", OFFICIAL)["flags"]
