import type { Job, SourceAsset } from "@lifereel/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Paintbrush, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { api, evidenceAssetUrl } from "../api/client";
import { ERROR_MESSAGES, errorMessage } from "../api/errors";
import { AssetPreview } from "./AssetPreview";

export function PhotoRedraw({
  asset,
  onStart,
}: {
  asset: SourceAsset;
  onStart: () => void;
}) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"original" | "redraw" | null>(null);
  const key = ["photo-redraw", asset.id];
  const status = useQuery({
    queryKey: key,
    queryFn: () => api.photoRedrawStatus(asset.id),
    enabled: !asset.is_redraw,
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.job?.status ?? "")
        ? 2500
        : false,
  });
  const updateJob = (job: Job) => {
    queryClient.setQueryData(key, { enabled: true, job });
    setMode(null);
  };
  const start = useMutation({
    mutationFn: () => api.redrawPhoto(asset.id),
    onSuccess: updateJob,
  });
  const job = status.data?.job;
  const retry = useMutation({
    mutationFn: () => api.retryJob(job!.id),
    onSuccess: updateJob,
  });
  const busy =
    start.isPending ||
    retry.isPending ||
    ["queued", "running"].includes(job?.status ?? "");
  const resultId =
    job?.status === "completed" && typeof job.result?.asset_id === "string"
      ? job.result.asset_id
      : null;
  const showResult = resultId && mode !== "original";
  useEffect(() => {
    if (resultId)
      void queryClient.invalidateQueries({
        queryKey: ["evidence", asset.subject_id],
      });
  }, [resultId, queryClient, asset.subject_id]);
  const validSource =
    !asset.derived_from_asset_id &&
    ["image/png", "image/jpeg", "image/webp"].includes(asset.mime_type) &&
    asset.byte_size <= 10 * 1024 * 1024 &&
    asset.status === "ready" &&
    (!asset.consent_status || asset.consent_status === "granted");
  const canRetry =
    job?.status === "failed" &&
    job.attempt_count < 3 &&
    job.error_code !== "PHOTO_REDRAW_REJECTED";
  const error = start.error || retry.error || status.error;

  return (
    <div className="photo-redraw">
      <div className="photo-redraw-toolbar">
        {asset.is_restoration && <span>AI 修复图</span>}
        {asset.is_redraw ? (
          <span>AI 处理图片</span>
        ) : resultId ? (
          <>
            <div
              className="photo-redraw-modes"
              role="group"
              aria-label="照片版本"
            >
              <button
                type="button"
                aria-pressed={!showResult}
                onClick={() => setMode("original")}
              >
                原图
              </button>
              <button
                type="button"
                aria-pressed={Boolean(showResult)}
                onClick={() => setMode("redraw")}
              >
                转描图
              </button>
            </div>
            <a
              className="icon-button"
              href={evidenceAssetUrl(resultId)}
              target="_blank"
              rel="noreferrer"
              aria-label="打开转描图片"
              title="打开转描图片"
            >
              <ExternalLink size={17} />
            </a>
          </>
        ) : (
          <>
            <button
              className="secondary-button"
              type="button"
              disabled={
                !status.data?.enabled ||
                !validSource ||
                busy ||
                (job?.status === "failed" && !canRetry)
              }
              onClick={() => {
                onStart();
                if (canRetry) retry.mutate();
                else start.mutate();
              }}
            >
              {canRetry ? <RotateCcw size={16} /> : <Paintbrush size={16} />}
              {busy
                ? job?.status === "running"
                  ? "转描中"
                  : "等待转描"
                : canRetry
                  ? "重新转描"
                  : "轻度转描"}
            </button>
            <span role="status">
              {status.isPending
                ? "读取转描状态"
                : !status.data?.enabled
                  ? "暂未启用"
                  : !validSource
                    ? "当前素材不支持转描"
                    : ""}
            </span>
          </>
        )}
      </div>
      {(error || job?.status === "failed") && (
        <p className="photo-redraw-error" role="alert">
          {error
            ? errorMessage(error)
            : ERROR_MESSAGES[job?.error_code ?? ""] || "照片转描失败。"}
        </p>
      )}
      <div className="memory-file-stage is-photo">
        {showResult ? (
          <img
            className="asset-preview-image"
            src={evidenceAssetUrl(resultId)}
            alt={`${asset.original_filename} 转描图`}
          />
        ) : (
          <AssetPreview asset={asset} />
        )}
      </div>
    </div>
  );
}
