import { describe, expect, it } from "vitest";
import { FALLBACK_LIMITS, mediaKindOf, parseLinks, validateFiles } from "@/lib/files";
import { fixtureStatus } from "../fixtures/fixture-report";

const MB = 1024 * 1024;
const limits = fixtureStatus.limits; // image 1 MB, video 2 MB, audio 1 MB, 4 files

const f = (name: string, size: number, type = "", lastModified = 1) => ({ name, size, type, lastModified });

describe("mediaKindOf", () => {
  it("uses the MIME type first, then the extension", () => {
    expect(mediaKindOf(f("a.bin", 1, "image/png"))).toBe("image");
    expect(mediaKindOf(f("a.bin", 1, "video/mp4"))).toBe("video");
    expect(mediaKindOf(f("a.bin", 1, "audio/ogg"))).toBe("audio");
    expect(mediaKindOf(f("voice-note.OPUS", 1))).toBe("audio");
    expect(mediaKindOf(f("clip.mov", 1))).toBe("video");
    expect(mediaKindOf(f("scan.jpeg", 1))).toBe("image");
    expect(mediaKindOf(f("notes.pdf", 1, "application/pdf"))).toBeNull();
    expect(mediaKindOf(f("README", 1))).toBeNull();
  });
});

describe("validateFiles", () => {
  it("accepts files within the limits in order", () => {
    const files = [f("a.png", MB, "image/png"), f("b.mp4", 2 * MB, "video/mp4")];
    const result = validateFiles([], files, limits);
    expect(result.accepted.map((x) => x.name)).toEqual(["a.png", "b.mp4"]);
    expect(result.rejected).toEqual([]);
  });

  it("rejects files over the limit for their kind", () => {
    const result = validateFiles([], [f("big.png", MB + 1, "image/png"), f("ok.mp4", MB + 1, "video/mp4")], limits);
    expect(result.accepted.map((x) => x.name)).toEqual(["ok.mp4"]);
    expect(result.rejected).toHaveLength(1);
    expect(result.rejected[0]?.name).toBe("big.png");
    expect(result.rejected[0]?.reason).toMatch(/limit for image files is 1 MB/);
  });

  it("rejects unsupported, empty and duplicate files", () => {
    const existing = [f("a.png", 10, "image/png")];
    const result = validateFiles(existing, [f("doc.pdf", 10, "application/pdf"), f("empty.png", 0, "image/png"), f("a.png", 10, "image/png")], limits);
    expect(result.accepted).toEqual([]);
    expect(result.rejected.map((r) => r.reason)).toEqual([
      "This is not an image, video or audio file.",
      "This file is empty.",
      "This file is already added.",
    ]);
  });

  it("stops at the maximum number of files", () => {
    const existing = [f("1.png", 1, "image/png", 1), f("2.png", 1, "image/png", 2), f("3.png", 1, "image/png", 3)];
    const result = validateFiles(existing, [f("4.png", 1, "image/png", 4), f("5.png", 1, "image/png", 5)], limits);
    expect(result.accepted.map((x) => x.name)).toEqual(["4.png"]);
    expect(result.rejected[0]?.reason).toMatch(/Only 4 files/);
  });

  it("works with real File objects and the fallback limits", () => {
    const file = new File([new Uint8Array(2048)], "photo.webp", { type: "image/webp" });
    expect(validateFiles([], [file], FALLBACK_LIMITS).accepted).toEqual([file]);
  });
});

describe("parseLinks", () => {
  it("returns trimmed non-empty lines", () => {
    expect(parseLinks(" https://a.example \r\n\n  \nhttp://b.example\n")).toEqual(["https://a.example", "http://b.example"]);
  });
});
