import type { SourceAsset } from "@lifereel/contracts";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AssetPreview } from "../components/AssetPreview";

function asset(kind: SourceAsset["kind"], mimeType: string): SourceAsset {
  return {
    id: `${kind}-asset`,
    subject_id: "subject-id",
    interview_session_id: null,
    kind,
    original_filename: `家庭素材.${kind}`,
    mime_type: mimeType,
    byte_size: 2048,
    sha256: "sha256",
    status: "ready",
    consent_scope: "private",
    captured_at: "2026-09-02T08:00:00Z",
    created_at: "2026-09-02T08:00:00Z",
  };
}

describe("AssetPreview", () => {
  it("renders image and document previews", () => {
    const { rerender } = render(<AssetPreview asset={asset("photo", "image/png")} />);
    expect(screen.getByRole("img", { name: "家庭素材.photo" })).toHaveAttribute(
      "src",
      "/v1/evidence/assets/photo-asset/content",
    );

    rerender(<AssetPreview asset={asset("document", "application/pdf")} />);
    expect(screen.getByTitle("家庭素材.document 文档预览")).toHaveAttribute(
      "src",
      "/v1/evidence/assets/document-asset/content",
    );
  });

  it("renders native audio and video controls without autoplay", () => {
    const { container, rerender } = render(
      <AssetPreview asset={asset("audio", "audio/mpeg")} />,
    );
    const audio = container.querySelector("audio");
    expect(audio).toHaveAttribute("controls");
    expect(audio).not.toHaveAttribute("autoplay");
    expect(audio).toHaveAttribute("src", "/v1/evidence/assets/audio-asset/content");

    rerender(<AssetPreview asset={asset("video", "video/mp4")} />);
    const video = container.querySelector("video");
    expect(video).toHaveAttribute("controls");
    expect(video).not.toHaveAttribute("autoplay");
    expect(video?.querySelector("source")).toHaveAttribute(
      "src",
      "/v1/evidence/assets/video-asset/content",
    );
  });
});
