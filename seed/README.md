Optional files copied into the API's data folder when the container starts (Cloud Run has no
persistent disk). Put a known-media index here, built from real, linked fact-checks with
`python scripts/build_known_index.py`, as `seed/image_index/` and `seed/audio_index/`.
Never put test fixtures or made-up items here. Leave the folder with only this file if you have none.
