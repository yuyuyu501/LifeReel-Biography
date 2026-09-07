import { describe, expect, it } from "vitest";
import { EVIDENCE_LIMITS, evidenceKindFromMime } from "./evidenceLimits";

describe("素材上传限制", () => {
  it("按 MIME 类型识别素材类别", () => {
    expect(evidenceKindFromMime("image/png")).toBe("photo");
    expect(evidenceKindFromMime("application/pdf")).toBe("document");
    expect(evidenceKindFromMime("audio/webm")).toBe("audio");
    expect(evidenceKindFromMime("video/mp4")).toBe("video");
    expect(evidenceKindFromMime("application/zip")).toBeNull();
  });

  it("为不同类型配置独立上限", () => {
    expect(EVIDENCE_LIMITS.photo.bytes).toBe(20 * 1024 ** 2);
    expect(EVIDENCE_LIMITS.document.bytes).toBe(50 * 1024 ** 2);
    expect(EVIDENCE_LIMITS.audio.bytes).toBe(500 * 1024 ** 2);
    expect(EVIDENCE_LIMITS.video.bytes).toBe(2 * 1024 ** 3);
  });
});
