import { describe, expect, it } from "vitest";
import { providerName, textConsentDetail } from "@/components/verify/VerifyForm";

describe("consent text names the AI provider", () => {
  it("names known providers and keeps unknown hosts as they are", () => {
    expect(providerName("generativelanguage.googleapis.com")).toBe("Google Gemini");
    expect(providerName("router.huggingface.co")).toBe("Hugging Face");
    expect(providerName("ai.example.org")).toBe("ai.example.org");
    expect(providerName(null)).toBeNull();
  });

  it("warns about Gemini free-tier data use only for Gemini", () => {
    expect(textConsentDetail("generativelanguage.googleapis.com")).toMatch(/may use submitted text to improve its products/);
    expect(textConsentDetail("router.huggingface.co")).not.toMatch(/improve its products/);
    expect(textConsentDetail(null)).toMatch(/^The AI model reads the text/);
  });
});
