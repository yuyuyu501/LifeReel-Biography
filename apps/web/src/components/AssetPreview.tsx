import type { SourceAsset } from "@lifereel/contracts";
import { FileAudio } from "lucide-react";
import { evidenceAssetUrl } from "../api/client";
import { formatAssetBytes } from "../assetFormatting";
import { statusLabel } from "../statusLabels";

export function AssetPreview({ asset }: { asset: SourceAsset }) {
  const source = evidenceAssetUrl(asset.id);

  if (asset.kind === "photo") {
    return <img className="asset-preview-image" src={source} alt={asset.original_filename} loading="lazy" />;
  }
  if (asset.kind === "video") {
    return (
      <video className="asset-preview-video" controls preload="metadata">
        <source src={source} type={asset.mime_type} />
      </video>
    );
  }
  if (asset.kind === "audio") {
    return (
      <div className="asset-preview-audio">
        <span className="asset-audio-mark"><FileAudio size={36} aria-hidden="true" /></span>
        <div>
          <strong>{asset.original_filename}</strong>
          <span>{formatAssetBytes(asset.byte_size)} · {statusLabel(asset.consent_scope)}</span>
        </div>
        <audio controls preload="metadata" src={source}>当前浏览器不支持音频播放。</audio>
      </div>
    );
  }
  return (
    <iframe
      className="asset-preview-document"
      src={source}
      title={`${asset.original_filename} 文档预览`}
    />
  );
}
