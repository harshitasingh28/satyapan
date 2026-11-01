"""Known-media index for images: perceptual hashes for speed, ORB + RANSAC for proof.

Stage 1  pHash/dHash of border-trimmed image and centre crops (100/90/80%). Survives
         resizing, recompression and screenshot bars. Fails on heavy or off-centre crops.
Stage 2  ORB keypoints + RANSAC homography. Survives off-centre crops, overlays and
         small rotations. Slower, so it runs on stage-1 candidates, or on every item
         when the index is small (spike setting).
The index stores hashes and keypoint descriptors only, never the images, so we
keep links to fact-check sources without redistributing their pictures.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image, ImageChops, ImageOps

CROP_SCALES = (1.0, 0.9, 0.8)
ORB_FEATURES = 1000
MIN_INLIERS = 25
MIN_INLIER_RATIO = 0.30
MIN_SPREAD = 0.10        # inliers must cover >= 10% of the reference keypoint area
MAX_ANISOTROPY = 3.0     # ratio of the homography's two scale factors
# Share of homography inliers that a similarity or affine map also explains. Set on the DEV set only
# (1 Nov 2026): every true-duplicate query with keypoint verification (12 images x 16 edits, including
# two stretches) had >= 0.847.
DUPLICATE_SIM_SHARE = 0.80
EXACT_PHASH = 2


def tier(hit: dict) -> str:
    """exact_duplicate | modified_duplicate | similar_scene. Only the first two can ever be evidence."""
    o = hit.get("orb") or {}
    orb_ok = o.get("inliers", 0) >= MIN_INLIERS and o.get("ratio", 0) >= MIN_INLIER_RATIO
    near_identical = hit.get("phash_dist") is not None and hit["phash_dist"] <= EXACT_PHASH and hit.get("crop_scale", 1.0) == 1.0
    if orb_ok and o.get("sim_share", 0) >= DUPLICATE_SIM_SHARE:
        return "exact_duplicate" if near_identical else "modified_duplicate"
    if near_identical:
        # pHash within 2 bits on the whole image: the same picture, possibly stretched so far that the
        # keypoint check fails (dev: 9 of 24 stretched copies matched only this way).
        return "exact_duplicate" if not o else "modified_duplicate"
    return "similar_scene"


def load_rgb(source: Path | Image.Image) -> Image.Image:
    if isinstance(source, Image.Image):
        return source.convert("RGB")
    with Image.open(source) as im:
        out = ImageOps.exif_transpose(im).convert("RGB")
        out.load()
    return out


def trim_borders(im: Image.Image, tolerance: int = 12) -> Image.Image:
    bg = Image.new("RGB", im.size, im.getpixel((0, 0)))
    mask = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > tolerance else 0)
    box = mask.getbbox()
    if not box or (box[2] - box[0]) < im.width * 0.3 or (box[3] - box[1]) < im.height * 0.3:
        return im
    return im.crop(box)


def centre_crop(im: Image.Image, scale: float) -> Image.Image:
    if scale >= 1.0:
        return im
    w, h = im.size
    dx, dy = int(w * (1 - scale) / 2), int(h * (1 - scale) / 2)
    return im.crop((dx, dy, w - dx, h - dy))


def orb_features(im: Image.Image, max_side: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    gray = np.array(ImageOps.grayscale(im))
    scale = max_side / max(gray.shape)
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    orb = cv2.ORB_create(nfeatures=ORB_FEATURES)
    kps, desc = orb.detectAndCompute(gray, None)
    if desc is None:
        return np.zeros((0, 2), np.float32), np.zeros((0, 32), np.uint8)
    return np.array([k.pt for k in kps], np.float32), desc


def orb_verify(q: tuple[np.ndarray, np.ndarray], r: tuple[np.ndarray, np.ndarray]) -> dict:
    (qpts, qdesc), (rpts, rdesc) = q, r
    if len(qdesc) < 10 or len(rdesc) < 10:
        return {"inliers": 0, "ratio": 0.0, "good": 0}
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(qdesc, rdesc, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 10:
        return {"inliers": 0, "ratio": 0.0, "good": len(good)}
    src = qpts[[m.queryIdx for m in good]].reshape(-1, 1, 2)
    dst = rpts[[m.trainIdx for m in good]].reshape(-1, 1, 2)
    hom, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if hom is None or mask is None:
        return {"inliers": 0, "ratio": 0.0, "good": len(good)}
    inliers = int(mask.sum())
    # Sanity checks against degenerate fits (found in the benchmark: a blurred image with
    # clustered keypoints "matched" unrelated photos).
    det = float(np.linalg.det(hom[:2, :2]))
    sv = np.linalg.svd(hom[:2, :2], compute_uv=False)
    anisotropy = float(sv[0] / sv[1]) if sv[1] > 1e-9 else float("inf")
    pts = dst.reshape(-1, 2)[mask.ravel() == 1]
    ref_w, ref_h = np.ptp(rpts[:, 0]) or 1.0, np.ptp(rpts[:, 1]) or 1.0
    spread = float((np.ptp(pts[:, 0]) * np.ptp(pts[:, 1])) / (ref_w * ref_h)) if len(pts) else 0.0
    # Copies, crops, resizes and small rotations are near-similarity transforms: both
    # scale factors are about equal. Degenerate fits stretch one axis far more than the other.
    sane = 0.01 < abs(det) < 100 and anisotropy <= MAX_ANISOTROPY and spread >= MIN_SPREAD
    # 2.0: copies (crop, resize, screenshot, small rotation, stretch) are explained by an affine map.
    # A different photo of the same scene usually is not (viewpoint change, parallax).
    # A full affine map (6 parameters) also covers stretched copies, such as a photo squeezed into a
    # 16:9 video frame, while still rejecting the perspective change of a different viewpoint.
    sim_inliers = 0
    for estimate in (cv2.estimateAffinePartial2D, cv2.estimateAffine2D):     # similarity, then full affine
        fit, fit_mask = estimate(src, dst, method=cv2.RANSAC, ransacReprojThreshold=5.0)
        if fit is not None and fit_mask is not None:
            sim_inliers = max(sim_inliers, int(fit_mask.sum()))
    return {"inliers": inliers if sane else 0, "ratio": round(inliers / len(good), 3), "good": len(good),
            "det": round(det, 3), "anisotropy": round(anisotropy, 2), "spread": round(spread, 3), "sane": sane,
            "sim_inliers": sim_inliers, "sim_ratio": round(sim_inliers / len(good), 3),
            "sim_share": round(sim_inliers / inliers, 3) if inliers else 0.0}


@dataclass
class IndexItem:
    id: str
    hashes: list[tuple[str, str, float]]          # (phash, dhash, crop scale)
    meta: dict = field(default_factory=dict)
    orb: tuple[np.ndarray, np.ndarray] | None = None


class ImageIndex:
    def __init__(self) -> None:
        self.items: list[IndexItem] = []

    def add(self, item_id: str, source: Path | Image.Image, **meta) -> None:
        im = trim_borders(load_rgb(source))
        hashes = []
        for s in CROP_SCALES:
            c = centre_crop(im, s)
            hashes.append((str(imagehash.phash(c)), str(imagehash.dhash(c)), s))
        self.items.append(IndexItem(item_id, hashes, meta, orb_features(im)))

    # ORB verification costs ~4 ms per indexed image (measured), so brute force is
    # limited to small indexes. Above that, only pHash candidates are verified.
    def query(self, source: Path | Image.Image, phash_max: int = 12, orb_all_below: int = 250,
              try_mirror: bool = True) -> list[dict]:
        im = trim_borders(load_rgb(source))
        hits = self._query(im, phash_max, orb_all_below)
        if not hits and try_mirror:
            hits = [{**h, "mirrored": True} for h in self._query(ImageOps.mirror(im), phash_max, orb_all_below)]
        return hits

    def _query(self, im: Image.Image, phash_max: int, orb_all_below: int) -> list[dict]:
        qp, qd = imagehash.phash(im), imagehash.dhash(im)
        results: dict[str, dict] = {}
        for it in self.items:
            best = min(((qp - imagehash.hex_to_hash(p)), (qd - imagehash.hex_to_hash(d)), s) for p, d, s in it.hashes)
            if best[0] <= phash_max:
                results[it.id] = {"id": it.id, "method": "phash", "phash_dist": int(best[0]),
                                  "dhash_dist": int(best[1]), "crop_scale": best[2], "meta": it.meta}
        q_orb = orb_features(im)
        candidates = self.items if len(self.items) <= orb_all_below else [i for i in self.items if i.id in results]
        for it in candidates:
            if it.orb is None:
                continue
            v = orb_verify(q_orb, it.orb)
            if v["inliers"] >= MIN_INLIERS and v["ratio"] >= MIN_INLIER_RATIO:
                r = results.setdefault(it.id, {"id": it.id, "meta": it.meta})
                r.update({"method": "phash+orb" if r.get("method") == "phash" else "orb", "orb": v})
            elif it.id in results:
                results[it.id]["orb"] = v
        for r in results.values():
            r["tier"] = tier(r)
        rank = {"exact_duplicate": 0, "modified_duplicate": 1, "similar_scene": 2}
        return sorted(results.values(), key=lambda r: (rank[r["tier"]], -(r.get("orb", {}).get("inliers", 0)),
                                                       r.get("phash_dist", 99)))

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        meta = [{"id": it.id, "hashes": it.hashes, "meta": it.meta} for it in self.items]
        (folder / "index.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        np.savez_compressed(folder / "orb.npz", **{f"{i}_p": it.orb[0] for i, it in enumerate(self.items) if it.orb},
                            **{f"{i}_d": it.orb[1] for i, it in enumerate(self.items) if it.orb})

    @classmethod
    def load(cls, folder: Path) -> "ImageIndex":
        idx = cls()
        rows = json.loads((folder / "index.json").read_text(encoding="utf-8"))
        orb = np.load(folder / "orb.npz") if (folder / "orb.npz").exists() else {}
        for i, r in enumerate(rows):
            feats = (orb[f"{i}_p"], orb[f"{i}_d"]) if f"{i}_p" in orb else None
            idx.items.append(IndexItem(r["id"], [tuple(h) for h in r["hashes"]], r["meta"], feats))
        return idx
