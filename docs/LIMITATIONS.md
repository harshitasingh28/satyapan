# Known limitations

## Detection limits
- **No deepfake detection.** Video face swaps, lip-sync edits and cloned voices are not detected. The published evidence says detectors usable by a student team fail on real-world media.
- **Detector scores are signals.** The AI-image score enters a verdict only after `eval/detector_eval.py` passes on real forwarded images.
- **Provenance needs an index.** Reuse is found only against the team's known-debunk index or through Cloud Vision, which needs billing and consent. An empty index means "no match", which says nothing.
- **Low-texture images can be missed** by the image index (measured on blurred and microscopy images).
- **Web Detection gives no dates.** Dating "first seen" needs a human until page dates are extracted.

## Matching and coverage limits
- **Claim matching is lexical.** A Telugu claim will not match an English fact-check. Multilingual embeddings are the first upgrade if dev errors show this.
- **Coverage gaps.** PIB debunks are not in ClaimReview, and PIB publishes them on social platforms only, so they must be curated by hand with links. Fact Check API coverage of Indian claims is unmeasured.
- **PIB RSS gaps.** Items have no dates (probed), and the documented English feed URL returned Hindi titles. The ingest job keeps "first seen" times and tries both URLs.
- **Official-record support is strict on purpose.** It needs 70% term overlap, matching amounts and official links. Expect many genuine messages to be UNVERIFIED rather than GENUINE.

## Heuristics and inputs
- **Impersonation rules are heuristics.** "Government plus a link that imitates a specific official site" is strong evidence. A generic "gov" in a non-gov.in name is only moderate (it flagged mygov.in and travel.state.gov as FAKE before the audit fix). The trade-off: a scam on a generic name like `pm-relief-gov.top` is now UNVERIFIED offline and needs a second signal (a new or unregistered domain from RDAP, Safe Browsing) to become FAKE. Keep `templates/official_domains.txt` (or `data/official_domains.txt`) up to date.
- **OCR is unmeasured on real screenshots.** Only rendered text was tested.

## External services
- **Nothing external is proven yet.** Every external API is untested live from our environment.
- **Free tiers are non-commercial.** This applies to Safe Browsing, VirusTotal, urlscan (written permission for commercial use) and Vercel Hobby.

## Hosting
- **No async queue.** Investigations run in threads, which is fine for a demo but not for load.
- **Dates are compared only in English and numeric forms** (15 November, Nov 15, 15/11/2026). Hindi and Telugu month names are not parsed, so a wrong date written in Hindi is not caught.
- **Links are normalised the way browsers do** (invisible characters dropped, full-width forms mapped to ASCII). This follows the IDNA idea but is not a complete UTS 46 implementation.


## Satyapan 2.0 (1 Nov 2026)

- **No measured accuracy yet.** The 2.0 rules are tested with fixtures. Accuracy needs the labelled real-world dataset in `eval/`, which has not been collected.
- **AI comparison quality is unmeasured** for Hindi and Telugu. Run `eval/model_bakeoff.py` on labelled pairs before choosing `HF_CHAT_MODEL`.
- **Semantic thresholds are provisional.** `SATYAPAN_SEMANTIC_CANDIDATE=0.80` only selects candidates for the AI comparison. Set it on the development split.
- **Outdated-news detection needs publication dates.** PIB's RSS feed has none. Record them with `scripts/ingest_pib.py --set-date`. Without a date, the report says the age could not be checked.
- **Image tiers:** on the earlier held-out set, false copies among different photos of the same scene fell from 15 of 36 to 1 of 36, and recall fell from 97.0% to 95.8%. That set was already seen in the 31 Oct audit, so a new team-photographed hard-negative set is still needed.
- **Not a deepfake detector.** No detector is integrated or validated.
- **Records are per browser.** Clearing browser storage loses the access tokens, and server copies expire after 7 days.
- **Rate limits and AI budgets are per Cloud Run instance**, not global.

## Added 1 Nov 2026 (evening)

- The AI planner is bounded: one model call that can add up to 3 fact-check searches and skip the official-release search only for an English, non-government claim. It cannot remove the safety checks, add evidence or set a verdict. It is not an autonomous agent.
- The AI-image detector (Sightengine, optional) is the vendor's judgement, not validated by Satyapan on forwarded images. It is shown as flagged, not flagged or unclear, never as a percentage, and never changes the verdict. Satyapan does not detect face swaps, video deepfakes or cloned voices.
- The debunked-media index is empty in the current deployment, so media reuse cannot produce a verdict there until real debunked items with their fact-check links are imported.
