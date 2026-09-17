import type {
  ScriptProject,
  ScriptScene,
  SourceAsset,
} from "@lifereel/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileAudio, Pencil, Save, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api, evidenceAssetUrl } from "../api/client";
import { ErrorNotice } from "./QueryState";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogFooter, DialogTitle } from "./ui/dialog";

function eligible(asset: SourceAsset) {
  return (
    !asset.is_redraw &&
    asset.status === "ready" &&
    (!asset.consent_status || asset.consent_status === "granted") &&
    asset.byte_size > 0 &&
    ((asset.kind === "photo" &&
      ["image/jpeg", "image/png", "image/webp"].includes(asset.mime_type) &&
      asset.byte_size <= 10 * 1024 * 1024) ||
      (asset.kind === "audio" &&
        ["audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav"].includes(
          asset.mime_type,
        ) &&
        asset.byte_size <= 15 * 1024 * 1024))
  );
}

function Media({ asset }: { asset: SourceAsset }) {
  return asset.kind === "photo" ? (
    <img src={evidenceAssetUrl(asset.id)} alt={asset.original_filename} />
  ) : (
    <div className="script-reference-audio">
      <FileAudio size={26} />
      <audio
        controls
        preload="none"
        src={evidenceAssetUrl(asset.id)}
        aria-label={asset.original_filename}
      />
    </div>
  );
}

export function ScriptReferences({
  project,
  scene,
  disabled,
  onEditingChange,
}: {
  project: ScriptProject;
  scene: ScriptScene;
  disabled?: boolean;
  onEditingChange?: (editing: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const key = [
    "script-references",
    project.id,
    scene.id,
    project.version_number,
  ];
  const references = useQuery({
    queryKey: key,
    queryFn: () => api.scriptReferences(project.id, scene.id),
  });
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [uploads, setUploads] = useState<SourceAsset[]>([]);
  const [fileError, setFileError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const library = useQuery({
    queryKey: ["evidence", project.subject_id],
    queryFn: () => api.listEvidence(project.subject_id),
    enabled: open,
  });
  const assets = [
    ...new Map(
      [...(library.data ?? []), ...(references.data ?? []), ...uploads]
        .filter(
          (asset) =>
            asset.subject_id === project.subject_id &&
            (eligible(asset) || selected.includes(asset.id)),
        )
        .map((asset) => [asset.id, asset]),
    ).values(),
  ];
  const close = () => {
    setOpen(false);
    onEditingChange?.(false);
  };
  const save = useMutation({
    mutationFn: () =>
      api.updateScriptReferences(
        project.id,
        scene.id,
        project.version_number,
        selected,
      ),
    onSuccess: async (updated) => {
      queryClient.setQueryData<ScriptProject[]>(["scripts"], (items) =>
        items?.map((item) => (item.id === updated.id ? updated : item)),
      );
      await queryClient.invalidateQueries({ queryKey: ["scripts"] });
      await queryClient.invalidateQueries({
        queryKey: ["script-references", project.id, scene.id],
      });
      close();
    },
  });
  const upload = useMutation({
    mutationFn: (file: File) =>
      api.uploadEvidence({
        subjectId: project.subject_id,
        kind: file.type.startsWith("audio/") ? "audio" : "photo",
        consentScope: "family",
        file,
      }),
    onSuccess: async (asset) => {
      setUploads((items) => [
        ...items.filter((item) => item.id !== asset.id),
        asset,
      ]);
      setSelected((ids) => [...new Set([...ids, asset.id])]);
      await queryClient.invalidateQueries({
        queryKey: ["evidence", project.subject_id],
      });
    },
  });
  const busy = save.isPending || upload.isPending;
  const selectedAssets = assets.filter((asset) => selected.includes(asset.id));
  const audioOnly =
    selectedAssets.some((asset) => asset.kind === "audio") &&
    !selectedAssets.some((asset) => asset.kind === "photo");
  return (
    <section className="script-references" aria-label="本章形象">
      <div className="script-reference-heading">
        <h4>形象</h4>
        <Button
          variant="ghost"
          size="icon"
          title="编辑本章形象"
          aria-label="编辑本章形象"
          disabled={disabled || references.isPending}
          onClick={() => {
            setSelected(
              references.data?.map((asset) => asset.id) ??
                scene.reference_asset_ids ??
                [],
            );
            setFileError("");
            save.reset();
            upload.reset();
            setOpen(true);
            onEditingChange?.(true);
          }}
        >
          <Pencil size={16} />
        </Button>
      </div>
      <ErrorNotice error={references.error} />
      <div className="script-reference-grid" aria-busy={references.isPending}>
        {references.data?.map((asset) => (
          <figure className="script-reference-item" key={asset.id}>
            <Media asset={asset} />
            <figcaption>{asset.original_filename}</figcaption>
          </figure>
        ))}
      </div>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!value && !busy) close();
        }}
      >
        <DialogContent
          className="script-reference-dialog"
          aria-describedby={undefined}
          showCloseButton={!busy}
        >
          <DialogTitle>本章形象</DialogTitle>
          <ErrorNotice error={save.error || upload.error || library.error} />
          {fileError && (
            <p role="alert" className="form-error">
              {fileError}
            </p>
          )}
          <div className="script-reference-library">
            {assets.map((asset) => (
              <div className="script-reference-item" key={asset.id}>
                <Media asset={asset} />
                <label>
                  <input
                    type="checkbox"
                    checked={selected.includes(asset.id)}
                    disabled={busy}
                    onChange={(event) =>
                      setSelected((ids) =>
                        event.target.checked
                          ? [...ids, asset.id]
                          : ids.filter((id) => id !== asset.id),
                      )
                    }
                  />
                  <span>{asset.original_filename}</span>
                </label>
              </div>
            ))}
          </div>
          {audioOnly && (
            <p className="form-error">音频参考需搭配至少一张图片。</p>
          )}
          <input
            ref={input}
            type="file"
            hidden
            accept="image/jpeg,image/png,image/webp,audio/mpeg,audio/mp3,audio/wav,audio/x-wav"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              const isAudio = file.type.startsWith("audio/");
              const limit = isAudio ? 15 : 10;
              if (!file.size || file.size > limit * 1024 * 1024) {
                setFileError(`文件须大于 0 且不超过 ${limit} MB。`);
                return;
              }
              setFileError("");
              upload.mutate(file);
            }}
          />
          <DialogFooter>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => input.current?.click()}
            >
              <Upload size={16} />
              {upload.isPending ? "上传中" : "上传素材"}
            </Button>
            <Button disabled={busy} onClick={() => save.mutate()}>
              <Save size={16} />
              {save.isPending ? "保存中" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
