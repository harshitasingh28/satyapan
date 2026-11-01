"""A link that hides an official domain inside another one is impersonation in any language,
and a message that is only a link still gets its link checked (offline, no keys needed)."""
from satyapan.pipeline.graph import Context, new_state, run, to_report


def verdict(text):
    return to_report(run(new_state(text=text), Context.default())).verdict


def test_telugu_message_with_hidden_official_domain_is_fake():
    msg = ("\u0c2a\u0c40\u0c0e\u0c02 \u0c15\u0c3f\u0c38\u0c3e\u0c28\u0c4d: e-KYC "
           "https://pmkisan.gov.in.ekyc-update.top/verify")
    assert verdict(msg) == "FAKE"


def test_message_that_is_only_a_lookalike_link_is_fake():
    assert verdict("https://uidai.gov.in.verify-kyc.top/login") == "FAKE"


def test_message_that_is_only_an_official_link_is_not_fake():
    assert verdict("https://www.india.gov.in") != "FAKE"


def test_message_that_is_only_an_ordinary_link_is_not_fake():
    assert verdict("https://example.com/news") != "FAKE"
