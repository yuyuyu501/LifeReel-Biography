import { useState } from "react";
import { ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "./ui/button";

export function PhotoComparison({
  original,
  restored,
  name,
}: {
  original: string;
  restored?: string;
  name: string;
}) {
  const [split, setSplit] = useState(50);
  const [zoom, setZoom] = useState(1);
  const [failed, setFailed] = useState(false);
  return (
    <div className="photo-comparison">
      <div className="restoration-preview-tools">
        <span>{restored ? "修复前 / 修复后" : "原图"}</span>
        <div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="缩小照片"
            title="缩小照片"
            disabled={zoom <= 1}
            onClick={() => setZoom((value) => Math.max(1, value - 0.5))}
          >
            <ZoomOut size={18} />
          </Button>
          <output aria-label="缩放比例">{zoom * 100}%</output>
          <Button
            variant="ghost"
            size="icon"
            aria-label="放大照片"
            title="放大照片"
            disabled={zoom >= 3}
            onClick={() => setZoom((value) => Math.min(3, value + 0.5))}
          >
            <ZoomIn size={18} />
          </Button>
        </div>
      </div>
      <div
        className="restoration-image-scroll"
        tabIndex={0}
        aria-label="照片预览"
      >
        <div
          className="restoration-image-canvas"
          style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }}
        >
          <img
            src={restored || original}
            alt={restored ? `${name} 修复后` : name}
            onError={() => setFailed(true)}
          />
          {restored && (
            <>
              <img
                className="restoration-before"
                src={original}
                alt={`${name} 修复前`}
                style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}
                onError={() => setFailed(true)}
              />
              <span
                className="restoration-divider"
                style={{ left: `${split}%` }}
                aria-hidden="true"
              />
            </>
          )}
        </div>
      </div>
      {failed && (
        <p className="form-error" role="alert">
          照片加载失败，请刷新页面重试。
        </p>
      )}
      {restored && (
        <div className="restoration-compare-slider">
          <span>原图</span>
          <input
            type="range"
            min="0"
            max="100"
            value={split}
            aria-label="修复前后对比"
            onChange={(event) => setSplit(Number(event.target.value))}
          />
          <span>修复后</span>
        </div>
      )}
    </div>
  );
}
