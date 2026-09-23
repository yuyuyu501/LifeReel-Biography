import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import type {
  ScriptProject,
  ScriptScene,
  ScriptSceneUpdate,
} from "@lifereel/contracts";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Pencil,
  Plus,
  Save,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ErrorNotice } from "./QueryState";
import { ScriptSections } from "./ScriptSections";
import { ScriptReferences } from "./ScriptReferences";

const shotTypes = {
  wide: "全景",
  medium: "中景",
  closeup: "特写",
  detail: "细节",
  archive: "档案镜头",
};

function draftFrom(
  project: ScriptProject,
  scene: ScriptScene,
): ScriptSceneUpdate {
  return {
    expected_version: project.version_number,
    heading: scene.heading,
    plot: scene.plot || "",
    dialogues: scene.dialogues?.length
      ? scene.dialogues.map((line) => ({ ...line }))
      : [{ kind: "narration", speaker: "旁白", text: scene.narration }],
    visual_prompt: scene.visual_prompt,
    duration_seconds: scene.duration_seconds,
    visual_constraints: scene.visual_constraints,
    story_skeleton: scene.story_skeleton,
    shots: (project.shots ?? [])
      .filter((shot) => shot.scene_id === scene.id)
      .sort((a, b) => a.order_index - b.order_index)
      .map(({ shot_type, visual_prompt, duration_seconds, visual_constraints }) => ({
        shot_type,
        visual_prompt,
        duration_seconds,
        visual_constraints,
      })),
  };
}

export function EditableScript({
  project,
  scene,
  disabled = false,
  onEditingChange,
}: {
  project: ScriptProject;
  scene: ScriptScene;
  disabled?: boolean;
  onEditingChange?: (editing: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<ScriptSceneUpdate | null>(null);
  const save = useMutation({
    mutationFn: (value: ScriptSceneUpdate) =>
      api.updateScriptScene(project.id, scene.id, value),
    onSuccess: async (updated) => {
      setDraft(null);
      onEditingChange?.(false);
      queryClient.setQueryData<ScriptProject[]>(["scripts"], (items) =>
        items?.map((item) => (item.id === updated.id ? updated : item)),
      );
      await queryClient.invalidateQueries({ queryKey: ["scripts"] });
      await queryClient.invalidateQueries({
        queryKey: ["interview-workspace"],
      });
    },
  });
  useEffect(() => {
    if (!draft) return;
    const prevent = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [draft]);
  const patch = (changes: Partial<ScriptSceneUpdate>) =>
    setDraft((value) => value && { ...value, ...changes });
  function move(kind: "shots" | "dialogues", index: number, delta: number) {
    if (!draft) return;
    const items = [...draft[kind]];
    [items[index], items[index + delta]] = [items[index + delta], items[index]];
    setDraft({ ...draft, [kind]: items });
  }
  const invalidDuration =
    !!draft?.shots.length &&
    draft.shots.reduce((sum, shot) => sum + shot.duration_seconds, 0) !==
      draft.duration_seconds;
  return (
    <div className="editable-script">
      <header className="script-editor-heading">
        <h3>{scene.heading}</h3>
        {!draft && (
          <Button
            variant="outline"
            size="icon"
            className="icon-button"
            title="编辑本章剧本"
            aria-label="编辑本章剧本"
            disabled={disabled}
            onClick={() => {
              save.reset();
              setDraft(draftFrom(project, scene));
              onEditingChange?.(true);
            }}
          >
            <Pencil size={18} />
          </Button>
        )}
      </header>
      {!draft ? (
        <>
          <ScriptReferences
            project={project}
            scene={scene}
            disabled={disabled}
            onEditingChange={onEditingChange}
          />
          <ScriptSections scene={scene} shots={project.shots} />
        </>
      ) : (
        <form
          className="script-editor"
          onSubmit={(event) => {
            event.preventDefault();
            if (!invalidDuration && !disabled && !save.isPending)
              save.mutate(draft);
          }}
        >
          <fieldset disabled={save.isPending || disabled}>
            <label>
              章节标题
              <Input
                required
                maxLength={180}
                value={draft.heading}
                onChange={(event) => patch({ heading: event.target.value })}
              />
            </label>
            <label>
              剧情
              <Textarea
                rows={4}
                maxLength={4000}
                value={draft.plot || ""}
                onChange={(event) => patch({ plot: event.target.value })}
              />
            </label>
            <section aria-label="编辑分镜">
              <div className="script-editor-subheading">
                <h4>分镜</h4>
                <Button
                  variant="outline"
                  size="icon"
                  type="button"
                  className="icon-button"
                  title="添加分镜"
                  aria-label="添加分镜"
                  disabled={draft.shots.length >= 40}
                  onClick={() =>
                    patch({
                      shots: [
                        ...draft.shots,
                        {
                          shot_type: "medium",
                          duration_seconds: 5,
                          visual_prompt: "",
                        },
                      ],
                    })
                  }
                >
                  <Plus size={17} />
                </Button>
              </div>
              {draft.shots.map((shot, index) => (
                <div className="script-editor-item" key={index}>
                  <div className="script-editor-item-heading">
                    <strong>镜头 {index + 1}</strong>
                    <div className="script-editor-tools">
                      <Button
                        variant="outline"
                        size="icon"
                        type="button"
                        className="icon-button"
                        title="上移分镜"
                        aria-label={`上移镜头 ${index + 1}`}
                        disabled={!index}
                        onClick={() => move("shots", index, -1)}
                      >
                        <ArrowUp size={16} />
                      </Button>
                      <Button
                        variant="outline"
                        size="icon"
                        type="button"
                        className="icon-button"
                        title="下移分镜"
                        aria-label={`下移镜头 ${index + 1}`}
                        disabled={index === draft.shots.length - 1}
                        onClick={() => move("shots", index, 1)}
                      >
                        <ArrowDown size={16} />
                      </Button>
                      <Button
                        variant="outline"
                        size="icon"
                        type="button"
                        className="icon-button"
                        title="删除分镜"
                        aria-label={`删除镜头 ${index + 1}`}
                        onClick={() =>
                          patch({
                            shots: draft.shots.filter((_, i) => i !== index),
                          })
                        }
                      >
                        <Trash2 size={16} />
                      </Button>
                    </div>
                  </div>
                  <div className="script-editor-fields">
                    <label>
                      景别
                      <select
                        aria-label={`镜头 ${index + 1} 景别`}
                        value={shot.shot_type}
                        onChange={(event) =>
                          patch({
                            shots: draft.shots.map((item, i) =>
                              i === index
                                ? { ...item, shot_type: event.target.value }
                                : item,
                            ),
                          })
                        }
                      >
                        {Object.entries(shotTypes).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      时长（秒）
                      <Input
                        aria-label={`镜头 ${index + 1} 时长`}
                        type="number"
                        min={1}
                        max={300}
                        required
                        value={shot.duration_seconds}
                        onChange={(event) =>
                          patch({
                            shots: draft.shots.map((item, i) =>
                              i === index
                                ? {
                                    ...item,
                                    duration_seconds: Number(
                                      event.target.value,
                                    ),
                                  }
                                : item,
                            ),
                          })
                        }
                      />
                    </label>
                  </div>
                  <label>
                    画面与动作
                    <Textarea
                      aria-label={`镜头 ${index + 1} 画面与动作`}
                      required
                      rows={3}
                      maxLength={4000}
                      value={shot.visual_prompt}
                      onChange={(event) =>
                        patch({
                          shots: draft.shots.map((item, i) =>
                            i === index
                              ? { ...item, visual_prompt: event.target.value }
                              : item,
                          ),
                        })
                      }
                    />
                  </label>
                  <label className="checkbox-field">
                    <input
                      type="checkbox"
                      checked={shot.visual_constraints?.face_policy === "no_identifiable_faces"}
                      onChange={(event) =>
                        patch({
                          shots: draft.shots.map((item, i) =>
                            i === index
                              ? {
                                  ...item,
                                  visual_constraints: {
                                    face_policy: event.target.checked
                                      ? "no_identifiable_faces"
                                      : "unspecified",
                                    required_elements: item.visual_constraints?.required_elements ?? [],
                                    forbidden_elements: item.visual_constraints?.forbidden_elements ?? [],
                                    notes: item.visual_constraints?.notes ?? null,
                                  },
                                }
                              : item,
                          ),
                        })
                      }
                    />
                    本镜头禁止出现可辨识正脸或侧脸
                  </label>
                </div>
              ))}
            </section>
            <label>
              章节总时长（秒）
              <Input
                type="number"
                min={4}
                max={300}
                required
                value={draft.duration_seconds}
                onChange={(event) =>
                  patch({ duration_seconds: Number(event.target.value) })
                }
              />
            </label>
            {invalidDuration && (
              <p className="form-error" role="alert">
                分镜时长之和须等于章节总时长。
              </p>
            )}
            <section aria-label="编辑人物对话">
              <div className="script-editor-subheading">
                <h4>人物对话</h4>
                <Button
                  variant="outline"
                  size="icon"
                  type="button"
                  className="icon-button"
                  title="添加台词"
                  aria-label="添加台词"
                  disabled={draft.dialogues.length >= 40}
                  onClick={() =>
                    patch({
                      dialogues: [
                        ...draft.dialogues,
                        { kind: "dialogue", speaker: "", text: "" },
                      ],
                    })
                  }
                >
                  <Plus size={17} />
                </Button>
              </div>
              {draft.dialogues.map((line, index) => (
                <div className="script-editor-item" key={index}>
                  <div className="script-editor-item-heading">
                    <strong>台词 {index + 1}</strong>
                    <div className="script-editor-tools">
                      <Button
                        variant="outline"
                        size="icon"
                        type="button"
                        className="icon-button"
                        title="上移台词"
                        aria-label={`上移台词 ${index + 1}`}
                        disabled={!index}
                        onClick={() => move("dialogues", index, -1)}
                      >
                        <ArrowUp size={16} />
                      </Button>
                      <Button
                        variant="outline"
                        size="icon"
                        type="button"
                        className="icon-button"
                        title="下移台词"
                        aria-label={`下移台词 ${index + 1}`}
                        disabled={index === draft.dialogues.length - 1}
                        onClick={() => move("dialogues", index, 1)}
                      >
                        <ArrowDown size={16} />
                      </Button>
                      <Button
                        variant="outline"
                        size="icon"
                        type="button"
                        className="icon-button"
                        title="删除台词"
                        aria-label={`删除台词 ${index + 1}`}
                        disabled={draft.dialogues.length === 1}
                        onClick={() =>
                          patch({
                            dialogues: draft.dialogues.filter(
                              (_, i) => i !== index,
                            ),
                          })
                        }
                      >
                        <Trash2 size={16} />
                      </Button>
                    </div>
                  </div>
                  <div className="script-editor-fields">
                    <label>
                      类型
                      <select
                        aria-label={`台词 ${index + 1} 类型`}
                        value={line.kind}
                        onChange={(event) =>
                          patch({
                            dialogues: draft.dialogues.map((item, i) =>
                              i === index
                                ? {
                                    ...item,
                                    kind: event.target.value as
                                      "narration" | "dialogue",
                                  }
                                : item,
                            ),
                          })
                        }
                      >
                        <option value="narration">旁白</option>
                        <option value="dialogue">人物对话</option>
                      </select>
                    </label>
                    <label>
                      说话人
                      <Input
                        aria-label={`台词 ${index + 1} 说话人`}
                        required
                        maxLength={100}
                        value={line.speaker}
                        onChange={(event) =>
                          patch({
                            dialogues: draft.dialogues.map((item, i) =>
                              i === index
                                ? { ...item, speaker: event.target.value }
                                : item,
                            ),
                          })
                        }
                      />
                    </label>
                  </div>
                  <label>
                    台词
                    <Textarea
                      aria-label={`台词 ${index + 1} 内容`}
                      required
                      rows={3}
                      maxLength={2000}
                      value={line.text}
                      onChange={(event) =>
                        patch({
                          dialogues: draft.dialogues.map((item, i) =>
                            i === index
                              ? { ...item, text: event.target.value }
                              : item,
                          ),
                        })
                      }
                    />
                  </label>
                </div>
              ))}
            </section>
            <label>
              场景描述
              <Textarea
                required
                rows={4}
                maxLength={4000}
                value={draft.visual_prompt}
                onChange={(event) =>
                  patch({ visual_prompt: event.target.value })
                }
              />
            </label>
          </fieldset>
          <ErrorNotice error={save.error} />
          <div className="script-editor-actions">
            <Button
              variant="outline"
              type="button"
              className="button secondary"
              disabled={save.isPending}
              onClick={() => {
                setDraft(null);
                onEditingChange?.(false);
                save.reset();
              }}
            >
              <X size={16} /> 取消
            </Button>
            <Button
              variant="default"
              className="button primary"
              disabled={save.isPending || invalidDuration || disabled}
            >
              <Save size={16} /> {save.isPending ? "正在保存" : "保存修改"}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
