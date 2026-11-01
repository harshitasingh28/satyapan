from satyapan.claims import detect_language, extract_claims, extract_urls
from satyapan.llm import grounded_claims
from satyapan.sources.textindex import BM25, tokenize


def test_hindi_english_scam_message():
    text = ("🚨 PM Kisan Yojana: सभी किसानों को ₹10,000 मिलेंगे। Apply now at http://pmkisan-gov.top/register?id=7&ref=wa "
            "before 30/11/2026. Call +91 98765 43210. Forward to all!")
    claims = extract_claims(text)
    c = claims[0]
    assert "http://pmkisan-gov.top/register?id=7&ref=wa" in c.urls      # '=' and '&' survive normalisation
    assert any("10,000" in a for a in c.amounts)
    assert "pm kisan" in c.entities and "yojana" in c.entities
    assert {"apply now", "forward"} <= set(c.calls_to_action)
    assert c.phones and "98765" in c.phones[0]
    assert "🚨" not in c.text and "pmkisan-gov.top" not in c.text      # URLs removed from claim text


def test_bare_domains_and_false_positives():
    urls = extract_urls("Visit pmkisan.gov.in or www.example.com/abc. Pay Rs.500 now. Version 2.0 out.")
    assert "http://pmkisan.gov.in" in urls and "http://www.example.com/abc" in urls
    assert not any("rs.500" in u.lower() or "2.0" in u for u in urls)


def test_language_detection():
    assert detect_language("सरकार मुफ्त लैपटॉप देगी") == "hi"
    assert detect_language("ప్రభుత్వం ఉచిత ల్యాప్‌టాప్ ఇస్తుంది") == "te"
    assert detect_language("Government will give free laptops") == "en"


def test_telugu_entities():
    c = extract_claims("ప్రభుత్వం కొత్త పథకం: ప్రతి కుటుంబానికి ఉచిత రేషన్. లింక్ క్లిక్ చేయండి")[0]
    assert "ప్రభుత్వం" in c.entities and "పథకం" in c.entities


def test_llm_grounding_rejects_invented_claims():
    source = "Government will give every student a free laptop. Register at laptop-yojana.top"
    kept, rejected = grounded_claims(source, [
        {"quote": "Government will give every student a free laptop"},
        {"quote": "The Ministry of Education confirmed the laptop scheme on Monday"},   # not in the text
    ])
    assert [k.text for k in kept] == ["Government will give every student a free laptop"]
    assert rejected and rejected[0]["reason"] == "not found in source text"


def test_bm25_keeps_hindi_words_whole():
    assert "किसानों" in tokenize("सभी किसानों को लाभ")          # vowel signs must not split words
    idx = BM25([{"text": "प्रधानमंत्री किसान सम्मान निधि की किस्त जारी"}, {"text": "Railway ticket booking rules"}])
    assert idx.search("किसान सम्मान निधि किस्त")[0]["doc"]["text"].startswith("प्रधानमंत्री")
