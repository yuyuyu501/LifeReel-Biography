import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FolderPlus,
  ImagePlus,
  LoaderCircle,
  RotateCcw,
  Sparkles,
  Upload,
} from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, API_BASE_URL } from "../api/client";
import type { PhotoRestoration, RestorationPhoto } from "../api/client";
import { ERROR_MESSAGES } from "../api/errors";
import { PhotoComparison } from "../components/PhotoComparison";
import { ErrorNotice, QueryState } from "../components/QueryState";
import { Button } from "../components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogTitle,
} from "../components/ui/dialog";

const photoUrl = (id: string) =>
  `${API_BASE_URL}/v1/photo-restoration/photos/${id}/content`;
const resultUrl = (id: string) =>
  `${API_BASE_URL}/v1/photo-restoration/runs/${id}/content`;
const pending = (status?: string) =>
  status === "queued" || status === "running";
const statusText = (status: string) =>
  ({
    queued: "等待修复",
    running: "正在修复",
    completed: "修复完成",
    failed: "修复失败",
  })[status] ?? status;

export function PhotoRestorationPage() {
  const cache = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [photo, setPhoto] = useState<RestorationPhoto | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [colorize, setColorize] = useState(false);
  const [page, setPage] = useState(1);
  const [fileError, setFileError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [subjectId, setSubjectId] = useState("");
  const [saved, setSaved] = useState("");
  const settings = useQuery({
    queryKey: ["restoration-settings"],
    queryFn: api.restorationSettings,
  });
  const history = useQuery({
    queryKey: ["restorations", page],
    queryFn: () => api.restorationHistory(page),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => pending(item.status))
        ? 4000
        : false,
  });
  const current = useQuery({
    queryKey: ["restoration", runId],
    queryFn: () => api.restorationRun(runId!),
    enabled: !!runId,
    refetchInterval: (query) =>
      pending(query.state.data?.status) ? 2500 : false,
  });
  const people = useQuery({
    queryKey: ["persons"],
    queryFn: api.listPersons,
    enabled: saveOpen,
  });
  const run = current.data;
  const activePhoto = run?.photo ?? photo;
  const selectRun = (item: PhotoRestoration) => {
    setRunId(item.id);
    setPhoto(item.photo);
    setColorize(item.colorize);
    setSaved("");
    cache.setQueryData(["restoration", item.id], item);
  };
  const upload = useMutation({
    mutationFn: (file: File) => api.uploadRestorationPhoto(file),
    onSuccess: (item) => {
      setPhoto(item);
      setRunId(null);
      setColorize(false);
      setSaved("");
    },
  });
  const start = useMutation({
    mutationFn: () => api.startRestoration(activePhoto!.id, colorize),
    onSuccess: async (item) => {
      selectRun(item);
      setPage(1);
      await cache.invalidateQueries({ queryKey: ["restorations"] });
    },
  });
  const retry = useMutation({
    mutationFn: () => api.retryJob(run!.id),
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: ["restoration", runId] });
      await cache.invalidateQueries({ queryKey: ["restorations"] });
    },
  });
  const save = useMutation({
    mutationFn: () => api.saveRestoration(run!.id, subjectId),
    onSuccess: async () => {
      setSaveOpen(false);
      setSaved("已保存到人物素材");
      await cache.invalidateQueries({ queryKey: ["evidence", subjectId] });
    },
  });
  const busy = upload.isPending || start.isPending || retry.isPending;
  const running = pending(run?.status);
  const sameOptions = run && run.colorize === colorize;
  const completed = run?.status === "completed";
  const acceptFile = (file?: File) => {
    if (!file || busy) return;
    setFileError("");
    start.reset();
    retry.reset();
    upload.reset();
    if (
      !["image/jpeg", "image/png", "image/webp"].includes(file.type) ||
      !file.size ||
      file.size > (settings.data?.max_bytes ?? 10485760)
    ) {
      setFileError("请选择不超过 10 MB 的 JPG、PNG 或 WebP 照片。");
      return;
    }
    upload.mutate(file);
  };
  return (
    <div className="page restoration-page">
      <header className="restoration-heading">
        <h1>照片修复</h1>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => fileInput.current?.click()}
        >
          <Upload size={17} />
          上传照片
        </Button>
      </header>
      <input
        ref={fileInput}
        type="file"
        hidden
        accept="image/jpeg,image/png,image/webp"
        aria-label="上传老照片"
        onChange={(event) => {
          acceptFile(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
      <ErrorNotice
        error={upload.error || start.error || retry.error || current.error}
      />
      {fileError && (
        <p className="form-error" role="alert">
          {fileError}
        </p>
      )}
      <QueryState queries={[settings]} />
      {settings.data && !settings.data.enabled && (
        <p className="notice">照片修复暂未启用。</p>
      )}
      <section
        className={`restoration-workspace${dragging ? " is-dragging" : ""}`}
        aria-label="修复工作区"
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          acceptFile(event.dataTransfer.files[0]);
        }}
      >
        {activePhoto ? (
          <PhotoComparison
            key={`${activePhoto.id}:${completed ? run.id : "original"}`}
            original={photoUrl(activePhoto.id)}
            restored={completed ? resultUrl(run.id) : undefined}
            name={activePhoto.original_filename}
          />
        ) : (
          <button
            className="restoration-upload-area"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
          >
            <ImagePlus size={40} strokeWidth={1.4} />
            <strong>{upload.isPending ? "正在上传" : "上传老照片"}</strong>
            <span>JPG / PNG / WebP · 最大 10 MB</span>
          </button>
        )}
        <div className="restoration-actions">
          <div className="restoration-options">
            <label>
              <input
                type="checkbox"
                checked={colorize}
                disabled={busy || running}
                onChange={(event) => setColorize(event.target.checked)}
              />
              上色
            </label>
            {activePhoto && (
              <span
                className="restoration-filename"
                title={activePhoto.original_filename}
              >
                {activePhoto.original_filename}
              </span>
            )}
          </div>
          <Button
            disabled={
              !activePhoto ||
              !settings.data?.enabled ||
              busy ||
              running ||
              (!!sameOptions && !run.can_retry)
            }
            onClick={() =>
              sameOptions && run.can_retry ? retry.mutate() : start.mutate()
            }
          >
            {busy || running ? (
              <LoaderCircle className="restoration-spinner" size={17} />
            ) : sameOptions && run.can_retry ? (
              <RotateCcw size={17} />
            ) : (
              <Sparkles size={17} />
            )}
            {upload.isPending
              ? "正在上传"
              : running
                ? statusText(run!.status)
                : busy
                  ? "正在提交"
                  : sameOptions && run.can_retry
                    ? "重新修复"
                    : sameOptions && completed
                      ? "修复完成"
                      : "开始修复"}
          </Button>
        </div>
        {run?.error_code && (
          <p className="notice error" role="alert">
            {ERROR_MESSAGES[run.error_code] ?? "照片修复失败，请稍后重试。"}
          </p>
        )}
        {completed && (
          <div className="restoration-result-actions">
            <span role="status">
              {saved || (run.colorize ? "修复并上色" : "保守修复")}
            </span>
            <Button variant="outline" asChild>
              <a href={`${resultUrl(run.id)}?download=true`}>
                <Download size={17} />
                下载
              </a>
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setSaveOpen(true);
                save.reset();
                setSubjectId("");
              }}
            >
              <FolderPlus size={17} />
              保存到人物素材
            </Button>
          </div>
        )}
      </section>
      <section
        className="restoration-history"
        aria-labelledby="restoration-history-title"
      >
        <div className="restoration-heading">
          <h2 id="restoration-history-title">修复记录</h2>
          <span>{history.data?.total ?? 0} 张</span>
        </div>
        <QueryState queries={[history]} loadingText="正在加载修复记录" />
        {history.data?.total === 0 && (
          <p className="restoration-empty">暂无修复记录</p>
        )}
        <div className="restoration-history-grid">
          {history.data?.items.map((item) => (
            <button
              className="restoration-history-item"
              key={item.id}
              disabled={busy}
              aria-pressed={runId === item.id}
              onClick={() => {
                selectRun(item);
                start.reset();
                retry.reset();
                setFileError("");
              }}
            >
              <img
                src={
                  item.status === "completed"
                    ? resultUrl(item.id)
                    : photoUrl(item.photo.id)
                }
                alt={item.photo.original_filename}
                loading="lazy"
              />
              <strong>{item.photo.original_filename}</strong>
              <span>
                {item.colorize ? "修复并上色" : "保守修复"}
                <span className={`restoration-status is-${item.status}`}>
                  {statusText(item.status)}
                </span>
              </span>
              <time dateTime={item.created_at}>
                {new Date(item.created_at).toLocaleString("zh-CN", {
                  month: "2-digit",
                  day: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </time>
            </button>
          ))}
        </div>
        {(history.data?.total ?? 0) > 12 && (
          <nav className="restoration-pagination" aria-label="修复记录分页">
            <Button
              variant="outline"
              size="icon"
              title="上一页"
              aria-label="上一页"
              disabled={page <= 1}
              onClick={() => setPage((value) => value - 1)}
            >
              <ChevronLeft size={18} />
            </Button>
            <span>
              {page} / {Math.ceil((history.data?.total ?? 0) / 12)}
            </span>
            <Button
              variant="outline"
              size="icon"
              title="下一页"
              aria-label="下一页"
              disabled={page * 12 >= (history.data?.total ?? 0)}
              onClick={() => setPage((value) => value + 1)}
            >
              <ChevronRight size={18} />
            </Button>
          </nav>
        )}
      </section>
      <Dialog
        open={saveOpen}
        onOpenChange={(value) => {
          if (!save.isPending) setSaveOpen(value);
        }}
      >
        <DialogContent
          aria-describedby={undefined}
          showCloseButton={!save.isPending}
        >
          <DialogTitle>保存到人物素材</DialogTitle>
          <QueryState queries={[people]} />
          <ErrorNotice error={save.error} />
          {people.data?.length === 0 ? (
            <Link to="/people">创建人物</Link>
          ) : (
            <label className="restoration-person-label">
              人物
              <select
                value={subjectId}
                onChange={(event) => setSubjectId(event.target.value)}
                disabled={save.isPending}
              >
                <option value="" disabled>
                  选择人物
                </option>
                {people.data?.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.preferred_name || person.display_name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <DialogFooter>
            <Button
              disabled={!subjectId || save.isPending}
              onClick={() => save.mutate()}
            >
              <FolderPlus size={17} />
              {save.isPending ? "正在保存" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
