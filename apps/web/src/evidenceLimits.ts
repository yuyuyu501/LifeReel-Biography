export type EvidenceKind = "photo" | "document" | "audio" | "video";

export const EVIDENCE_LIMITS: Record<
  EvidenceKind,
  { bytes: number; label: string; display: string }
> = {
  photo: { bytes: 20 * 1024 * 1024, label: "图片", display: "20 MB" },
  document: { bytes: 50 * 1024 * 1024, label: "文档", display: "50 MB" },
  audio: { bytes: 500 * 1024 * 1024, label: "音频", display: "500 MB" },
  video: { bytes: 2 * 1024 * 1024 * 1024, label: "视频", display: "2 GB" },
};

const EVIDENCE_KIND_ORDER: EvidenceKind[] = ["photo", "document", "audio", "video"];

export const EVIDENCE_LIMIT_ITEMS = EVIDENCE_KIND_ORDER.map((kind) => {
  const limit = EVIDENCE_LIMITS[kind];
  return { kind, text: `${limit.label} ${limit.display}` };
});

export const EVIDENCE_LIMIT_SUMMARY = `上传上限：${EVIDENCE_LIMIT_ITEMS.map((item) => item.text).join(" · ")}`;

export function evidenceKindFromMime(mimeType: string): EvidenceKind | null {
  if (mimeType.startsWith("image/")) return "photo";
  if (["application/pdf", "text/plain", "text/markdown"].includes(mimeType)) return "document";
  if (mimeType.startsWith("audio/")) return "audio";
  if (mimeType.startsWith("video/")) return "video";
  return null;
}
