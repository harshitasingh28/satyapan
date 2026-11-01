"""Download the held-out image set used by audit/image_eval.py (OpenCV sample images).

Source: https://github.com/opencv/opencv/tree/4.10.0/samples/data (Apache-2.0, see the
OpenCV LICENSE). Pinned to tag 4.10.0 and checked against SHA-256 hashes, so every run
evaluates the same bytes. These images are NEVER used to tune thresholds.
Usage: python scripts/fetch_heldout_images.py [--out data/heldout]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import httpx

BASE = "https://raw.githubusercontent.com/opencv/opencv/4.10.0/samples/data/"
LICENSE = "https://raw.githubusercontent.com/opencv/opencv/4.10.0/LICENSE"
SHA256 = {
    "Blender_Suzanne1.jpg": "bc3330e78e3456688e22b62fe033b8b2444fd016df567b1782bcc9baaead8e02",
    "Blender_Suzanne2.jpg": "6c0777ab795b888703857312916bd6275e04a79e55f84f00c5b8cfdb60cbaf40",
    "HappyFish.jpg": "ade5b67347d7f89b1539c93843f3f7178782a7e34eb1fe586f4a785c3e60a432",
    "WindowsLogo.jpg": "b16d7d76bb2287ff8ba8f3fa37a448f9a3b3ec4725fdcd681b44f0f9139855c1",
    "aero1.jpg": "d9a69191f6e3642ea361bc3c62e677b2f40fe6534b78da540f4155e0734b59ef",
    "aero3.jpg": "1c407146f8762b3b14a7953ff9bc4c01ed64c467d7277122e769bf7e816017a4",
    "apple.jpg": "e86879de3d9a807dedc742a8f464f39e6b74bbb531a1fba3583155d94997d1cd",
    "baboon.jpg": "1a1dd18d78eec44420af3b0b7f08ee3d41c982916cae3ce203d7ff35d754cc0f",
    "basketball1.png": "ba06f6701f7260998b430c39b6557f775497e6ce7b1a74f0b7ea6af371bf54a6",
    "basketball2.png": "b3047772e0dc6c9d83c26f64894ca1a897f799f855c5574ac24b2ef934c2978e",
    "board.jpg": "4c9a24ba67138ad5486d550f586cc5dd1161be112f1c1bea336d6c550cdf255f",
    "box.png": "1094629c1e2ebbc8a9ae2c9c63e18c1dff0f5f1481146e02f3b11a3d30feb20a",
    "box_in_scene.png": "8b0225ff76244a42bd1400c0904f8b7afea7d97b7d8115495e42e98ad347bd51",
    "building.jpg": "742a1baad62ac82e91e718e77eedf7e85c2eddc4badfb8c87c6cbc86c45a8b07",
    "butterfly.jpg": "34a99716b78ded10eae87b4880de739d3e68cc7dd1a96812bb28f469d5eeaea8",
    "cards.png": "acf2d347e8de7fbb0edbf457c8fb467cb6d16d4166c92f40e68f3831e06149ac",
    "detect_blob.png": "f31a972c7aa0fbf5c0559a9c76cb0ef88a56567362d05194aa0e7f2592b4cff0",
    "digits.png": "60c917758ef97cc090f35cd8e293e4de691ef942847da0ff80dedab33d57c662",
    "ellipses.jpg": "775f8bd606ba5184907a0851474dc39893e11a296e0af233e8b00f7afbde1866",
    "fruits.jpg": "9c031d80a1c52da5eca790db896baffec6a7e52bf786cdb7bbfca5c7f880e6a1",
    "gradient.png": "ac8c3921949a2b36cd9b9060800ca344f27e4493f76e2a96b109601c94b42cd3",
    "graf1.png": "1504b769303c7bde00fa578eeaad3c68e02aceabeb1242e556f1f8d19e4bdea5",
    "graf3.png": "492e0e96f21748d093e1a29f4dbfd46528bd75966937e85ce7c8abc0f361fc15",
    "home.jpg": "23b8cf46a1965d0ec33459b875aed43187802834db49e0daa9fa2cc842e9d8d2",
    "left01.jpg": "9621899098adffa1440c8264606bb7be535ccfd9ad126ae8e0bd9b0c5a5b8676",
    "left02.jpg": "052e700bbcc865c112958ec2ea105cb1bce4deca50ac8d6efae13adca9df7a2c",
    "left03.jpg": "c85b9426c3d8fcf161e1e727356105091009c3fd0b1b1a65bc2da91fea2724d2",
    "left04.jpg": "b490599dccfbfe5eb56d33363415b02227a9548ab8c9b8e7b05d3580e97266d9",
    "left05.jpg": "40bab8934fa76f82ec614a7fd0e6ebb4d9f74391d5e8b0c6f2f0ed6080c6c4de",
    "left06.jpg": "1cb164db61b3bd52f58a7e9340bb27c5e0278895bc80b6f292fba5cf9bccc4a1",
    "left07.jpg": "d2211fe9f971646b6ff88ed93a4f0d3f443741eb2894095cba15caade7c8c6e4",
    "lena.jpg": "7de7ed51a1594fff247f4cae2301eceacf5313d6011e37b4a4c8733f7bb72c07",
    "lena_tmpl.jpg": "b7f96269c46069446764b16385e1ad9cca7c5fb5f79a6e2749c2ddcb7e344883",
    "licenseplate_motion.jpg": "ea6fa9cea75df91bec656d1d3b903111a9c0708c6a3b88f405a5156de38ff9d6",
    "mask.png": "d367226b00919d9487a59b0173592b7ee631337728fdd01f1b76beeab9b3f97a",
    "messi5.jpg": "1d570e49654e84c7a943918537bd9e5e1ef82920152e147c834006e235be97c9",
    "notes.png": "b40d7e1f92df046f4853b006a0dd745bd3e55e48e57faa28c686a519fd062633",
    "orange.jpg": "152c20d2f380ac985de25e474e1a5f06ed34b932191342099b8272a63a15a079",
    "pic1.png": "0244e20a34fa2d30c60e60928d6d71f89d32e0e0266b4644980798cc2368765a",
    "pic2.png": "8c32d76f17c2eca78a1402fd1bb48144785e5397ff5a24de68c36b0f76b1f055",
    "pic3.png": "1e2fe4632c0d5350d48525cc88a01a0764d9043d51a4110309b999eb79297db0",
    "pic4.png": "0d43824171301d7fe8e14733e8f799dfd26fe66bdb9098783c58a47733a3f002",
    "pic5.png": "fa1f0dcc715867c5c8684f53d29ed2bfa013f8669aa1f73864fb7d315638a02b",
    "pic6.png": "436808a38b064f1f2ca8790d8787382f887c2135c4bc6b3cfc84a3bd7b228d6e",
    "rubberwhale1.png": "eb312435369dac9efcc92f7e098edbd9ed8d7e6dfede8b3b4d8e3702cd80b796",
    "rubberwhale2.png": "ee309a00d47b837b322ea5d9128775e0c46869b8014376286ba316a073d293ac",
    "smarties.png": "ad3f751c053fdcf432687c1bc0e56a61a9119d2bb2ae29365f8aa6534fc77417",
    "starry_night.jpg": "accda7a19a90f22a4a922fdc8c230167d7abf5f80882171e2cee125c5f12481d",
    "stuff.jpg": "21cd00afbdd0727f445dd91c0a09633e6345ed5b05a3d2355453a1f3c314c6c5",
    "sudoku.png": "3cd9ab173f7178c0a16bba9f867062b58b5d60918d5aeb8ced85cba0b24c353a",
    "templ.png": "8b339c9ac686f3a85952fe895e9b0b0225b8ca0c9fd204dc11dce8e555152279"
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data" / "heldout"))
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    bad = []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        (out / "LICENSE_opencv.txt").write_bytes(client.get(LICENSE).content)
        for name, digest in SHA256.items():
            path = out / name
            if not (path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest):
                path.write_bytes(client.get(BASE + name).raise_for_status().content)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                bad.append(name)
    print(f"{len(SHA256) - len(bad)}/{len(SHA256)} files verified in {out}")
    if bad:
        print("HASH MISMATCH:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
