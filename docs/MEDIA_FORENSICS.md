# Media and deepfake analysis: what is real, what is not

## Three rules hold everywhere in the code

1. **Missing C2PA credentials are never treated as evidence of manipulation.**
2. **A perceptual-hash match is never treated as proof of a deepfake.** It shows reuse.
3. **A detector score is never treated as a verdict.** It is shown as a signal, and it counts only after it passes our calibration test.

**Verification marks:**
- **T:** tested in this repository.
- **V:** we opened the source ourselves.
- **R:** our research agent quoted the source, and we did not re-open it.

## Images

| Technique | Detects | Cannot detect | Accuracy evidence | Hardware | Cost and free tier | Licence | Difficulty | Hackathon |
|---|---|---|---|---|---|---|---|---|
| pHash and dHash with border trim and centre crops | the same image after resize, recompression, mild crops, screenshot bars | heavy or off-centre crops, mirrored copies (without the mirror pass), new images | T: 92 to 100% recall@1 on resize, JPEG and centre crop. **0%** on off-centre crop and screenshot without ORB | CPU, about 37 ms to index an image | free | BSD (ImageHash) | low | yes |
| ORB keypoints with RANSAC and sanity checks | crops, screenshots, captions, small rotations | low-texture images (blurred, microscopy), heavy re-drawing | T: 83 to 100% recall@1 on every variant. 0 false matches on 15 held-out queries. **Thresholds were tuned on this same set, so the numbers are optimistic** | CPU, about 4 ms per indexed image | free | Apache-2.0 (OpenCV) | medium | yes |
| C2PA Content Credentials | signed provenance, declared AI generation (IPTC `trainedAlgorithmicMedia`) | anything after metadata is stripped | T: signed fixture read, unsigned fixture "none", re-encoded copy "none". R: DALL-E 3, Firefly, Google and Microsoft generators attach C2PA. Chat apps' compression removes metadata | CPU, about 4 ms | free | Apache-2.0 or MIT | low | yes |
| Cloud Vision Web Detection | pages and copies of the image on the web | when the image first appeared | none published | API | 1,000 units/month free, then $3.50 per 1,000, billing needed (V) | proprietary | low | yes, with a card |
| Fact Check `claims:imageSearch` | fact-checks about this exact image | images not in ClaimReview | none published | API | free key | Google API Terms | low | partial, public URLs only |
| Sightengine `genai` | fully or partly AI-generated images | face swaps. "Confidence may drop... on heavily degraded images or screenshots" (R) | vendor blog: 98.3% on one benchmark, not independent (R) | API | 2,000 operations/month, about 400 checks (V) | proprietary | low | yes, as a signal |
| Open-source detectors (Organika/sdxl-detector, Ateeqq/ai-vs-human-image-detector, others) | images like their training data | unseen generators, recompressed images | self-reported 0.94 to 0.99 on their own splits (R). Independent work shows failure on unseen generators: Chameleon, "almost all models classify AI-generated images as real ones", and social-network recompression costs "10% to 100%" (R) | CPU feasible (about 86M parameters, speed unmeasured) | free | apache-2.0 to cc-by-nc | medium | yes, as a signal |
| SynthID Detector | Google and partner watermarks | everything else | n/a | web portal | free | proprietary | manual | manual only |

## Video

| Technique | Detects | Cannot detect | Accuracy evidence | Hardware | Cost | Licence | Hackathon |
|---|---|---|---|---|---|---|---|
| FFmpeg keyframes, then the image index | reused clips (old video, new claim) | face swaps, lip-sync, voice replacement | T: re-encoded, cropped 15 s clip gave at least 4 distinct frames, and at least 4 matched their source photos. 60 s 720p clip in 1.5 s | CPU | free | LGPL/GPL (FFmpeg) | yes |
| Deepfake video detectors | face manipulation in data like their training data | new methods, compressed real-world video | V: the Deepfake Detection Challenge winner "achieved an accuracy of 65.18 percent against the black box dataset". V: on 2024 in-the-wild deepfakes, AUC fell "by 50% for video" versus older benchmarks. R: DeepfakeBench best cross-dataset AUC 0.79, GPU Docker | GPU-oriented | free code. Reality Defender video from $399/month, Sightengine video from $29/month (R) | MIT to CC BY-NC | **no, not as a verdict** |

## Audio

| Technique | Detects | Cannot detect | Accuracy evidence | Hardware | Cost | Licence | Hackathon |
|---|---|---|---|---|---|---|---|
| Landmark fingerprinting (`media/audio.py`) | the same recording re-shared, re-encoded or with noise | cloned voices, new recordings of the same words | T, on real LibriSpeech clips:<br>• 6 s excerpt at 16 kbps Opus: matched at the right offset with 192 aligned hits<br>• 5 s excerpt at 32 kbps MP3: matched with 118 hits<br>• pink noise added: matched<br>• unrelated music: no match, at most 2 hits | CPU, about 0.1 s per query | free | our own code (numpy, scipy). Chromaprint, the off-the-shelf alternative, is LGPL 2.1 (R) | yes |
| Voice-clone detectors (AASIST, wav2vec2 fine-tunes, commercial) | synthetic speech like their training data | real-world audio in general | V: Müller et al. 2022, "performance degradation of up to one thousand percent" on real-world audio. R: equal error rates rose from about 1 to 6% to about 37 to 66%. R: ASVspoof 5 says "EERs increase to over 10%" across datasets | CPU possible for small models | free code. Reality Defender audio in 50 free scans/month (R). Resemble $0.035 per second (R) | MIT to CC BY-NC-ND | **no, not as a verdict** |

## What Satyapan says to users

| Situation | Report wording |
|---|---|
| Media matches a known debunk | "This image matches media from a debunked item (link)." Reuse, with the source. |
| Web Detection finds other pages | "The image appears on N other pages. Dates need review." Context only. |
| Credentials present | Signer, validation state, and whether AI is declared. |
| No credentials | "Missing Content Credentials prove nothing." |
| AI-image score | "AI-generation score 0.93 (detector NOT calibrated)". Context only, until calibration passes. |
| Video | "Checked for reuse through keyframes. Face swaps and lip-sync edits are not detected." |
| Voice | "UNVERIFIED. Satyapan does not judge whether a voice is synthetic." |

## Can T1-D's "deepfake audit" be met honestly?

Partly. The evidence shows a student team cannot ship reliable deepfake *detection*. It can ship a deepfake **audit** that does five things:
1. It finds reused media through provenance.
2. It reads provenance credentials.
3. It shows calibrated or clearly labelled detector signals.
4. It refuses to guess.
5. It measures each of these separately.
