import type {
  ScriptAdaptationPlanUpdate,
  ScriptProject,
  SequencePlanItem,
  StoryBibleEntry,
} from "@lifereel/contracts";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Pencil, Save, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { ErrorNotice } from "./QueryState";

const roleLabels: Record<string, string> = {
  opening: "开场",
  setup: "铺垫",
  development: "发展",
  turning_point: "转折",
  aftermath: "余波",
  closing: "收束",
  transition: "转场",
  montage: "蒙太奇",
};

type PlanDraft = Omit<ScriptAdaptationPlanUpdate, "expected_version">;

function lines(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function ScriptPlanSummary({ project }: { project: ScriptProject }) {
  const queryClient = useQueryClient();
  const brief = project.adaptation_brief;
  const bible = project.story_bible;
  const sequence = project.sequence_plan?.items ?? [];
  const [draft, setDraft] = useState<PlanDraft | null>(null);
  const save = useMutation({
    mutationFn: (payload: PlanDraft) =>
      api.updateScriptAdaptationPlan(project.id, {
        ...payload,
        expected_version: project.version_number,
      }),
    onSuccess: async (updated) => {
      setDraft(null);
      queryClient.setQueryData<ScriptProject[]>(["scripts"], (items) =>
        items?.map((item) => (item.id === updated.id ? updated : item)),
      );
      await queryClient.invalidateQueries({ queryKey: ["scripts"] });
    },
  });
  useEffect(() => {
    if (!draft) return;
    const prevent = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [draft]);
  if (!brief && !bible && !sequence.length) return null;

  const updateEntry = (
    group: "characters" | "locations" | "key_objects",
    index: number,
    changes: Partial<StoryBibleEntry>,
  ) => {
    if (!draft) return;
    const entries = [...draft.story_bible[group]];
    entries[index] = { ...entries[index], ...changes };
    setDraft({
      ...draft,
      story_bible: { ...draft.story_bible, [group]: entries },
    });
  };
  const moveSequence = (index: number, delta: number) => {
    if (!draft) return;
    const items = [...draft.sequence_plan.items];
    [items[index], items[index + delta]] = [items[index + delta], items[index]];
    setDraft({
      ...draft,
      sequence_plan: {
        items: items.map((item, order) => ({
          ...item,
          order_index: order + 1,
        })),
      },
    });
  };
  const renderEntries = (
    label: string,
    group: "characters" | "locations" | "key_objects",
  ) => {
    const entries = draft?.story_bible[group] ?? bible?.[group] ?? [];
    if (!entries.length) return null;
    return (
      <section aria-label={label} key={group}>
        <h4>{label}</h4>
        <div className="script-plan-entry-list">
          {entries.map((entry, index) => (
            <label key={entry.id}>
              {entry.name}
              {draft ? (
                <Input
                  aria-label={`${label} ${index + 1}`}
                  maxLength={180}
                  value={entry.name}
                  onChange={(event) =>
                    updateEntry(group, index, { name: event.target.value })
                  }
                />
              ) : (
                <span>{entry.notes.map((note) => note.text).join("；")}</span>
              )}
            </label>
          ))}
        </div>
      </section>
    );
  };

  return (
    <details className="script-plan-summary">
      <summary>改编规划</summary>
      <div className="script-plan-summary-body">
        <div className="script-plan-toolbar">
          <h3>改编规划</h3>
          {!draft && (
            <Button
              variant="outline"
              size="icon"
              className="icon-button"
              title="编辑改编规划"
              aria-label="编辑改编规划"
              disabled={project.source_stale}
              onClick={(event) => {
                event.preventDefault();
                save.reset();
                setDraft({
                  adaptation_brief: structuredClone(brief!),
                  story_bible: structuredClone(bible!),
                  sequence_plan: structuredClone(project.sequence_plan!),
                });
              }}
            >
              <Pencil size={17} />
            </Button>
          )}
        </div>
        {project.source_stale && (
          <p role="status">书稿来源已变化，请重新生成剧本后再编辑规划。</p>
        )}
        {brief && (
          <section aria-labelledby="script-plan-theme">
            <h4 id="script-plan-theme">改编简报</h4>
            {draft ? (
              <>
                <label>
                  核心主题
                  <Textarea
                    rows={3}
                    maxLength={1000}
                    value={draft.adaptation_brief.theme}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        adaptation_brief: {
                          ...draft.adaptation_brief,
                          theme: event.target.value,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  叙事问题
                  <Input
                    maxLength={1000}
                    value={draft.adaptation_brief.dramatic_question ?? ""}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        adaptation_brief: {
                          ...draft.adaptation_brief,
                          dramatic_question: event.target.value || null,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  创作基调
                  <Input
                    maxLength={500}
                    value={draft.adaptation_brief.tone ?? ""}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        adaptation_brief: {
                          ...draft.adaptation_brief,
                          tone: event.target.value || null,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  必须避免（每行一项）
                  <Textarea
                    rows={3}
                    value={draft.adaptation_brief.must_avoid.join("\n")}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        adaptation_brief: {
                          ...draft.adaptation_brief,
                          must_avoid: lines(event.target.value),
                        },
                      })
                    }
                  />
                </label>
              </>
            ) : (
              <>
                <p>{brief.theme}</p>
                {brief.dramatic_question && <p>{brief.dramatic_question}</p>}
                {brief.tone && <small>基调：{brief.tone}</small>}
                {brief.must_avoid.length > 0 && (
                  <small>限制：{brief.must_avoid.join("；")}</small>
                )}
              </>
            )}
          </section>
        )}
        {bible && (
          <section aria-labelledby="script-plan-bible">
            <h4 id="script-plan-bible">故事圣经</h4>
            <p>
              人物 {bible.characters.length} · 地点 {bible.locations.length} ·
              时间线 {bible.timeline.length} · 关键物件{" "}
              {bible.key_objects.length}
            </p>
            {draft ? (
              <>
                {renderEntries("人物", "characters")}
                {renderEntries("地点", "locations")}
                {renderEntries("关键物件", "key_objects")}
                <label>
                  连续性约束（每行一项）
                  <Textarea
                    rows={3}
                    value={draft.story_bible.constraints.join("\n")}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        story_bible: {
                          ...draft.story_bible,
                          constraints: lines(event.target.value),
                        },
                      })
                    }
                  />
                </label>
              </>
            ) : (
              bible.constraints.length > 0 && (
                <small>连续性约束：{bible.constraints.join("；")}</small>
              )
            )}
          </section>
        )}
        {sequence.length > 0 && (
          <section aria-labelledby="script-plan-sequence">
            <h4 id="script-plan-sequence">场次计划</h4>
            <ol>
              {(draft?.sequence_plan.items ?? sequence).map(
                (item: SequencePlanItem, index) => (
                  <li key={item.key}>
                    {draft ? (
                      <>
                        <div className="script-plan-toolbar">
                          <strong>{item.order_index}. 场次</strong>
                          <div className="script-editor-tools">
                            <Button
                              variant="outline"
                              size="icon"
                              type="button"
                              className="icon-button"
                              title="上移场次"
                              aria-label={`上移场次 ${index + 1}`}
                              disabled={!index}
                              onClick={() => moveSequence(index, -1)}
                            >
                              <ArrowUp size={16} />
                            </Button>
                            <Button
                              variant="outline"
                              size="icon"
                              type="button"
                              className="icon-button"
                              title="下移场次"
                              aria-label={`下移场次 ${index + 1}`}
                              disabled={
                                index === draft.sequence_plan.items.length - 1
                              }
                              onClick={() => moveSequence(index, 1)}
                            >
                              <ArrowDown size={16} />
                            </Button>
                          </div>
                        </div>
                        <label>
                          场次标题
                          <Input
                            maxLength={180}
                            value={item.title}
                            onChange={(event) =>
                              setDraft({
                                ...draft,
                                sequence_plan: {
                                  items: draft.sequence_plan.items.map(
                                    (entry) =>
                                      entry.key === item.key
                                        ? {
                                            ...entry,
                                            title: event.target.value,
                                          }
                                        : entry,
                                  ),
                                },
                              })
                            }
                          />
                        </label>
                        <label>
                          场次梗概
                          <Textarea
                            rows={3}
                            maxLength={2000}
                            value={item.summary}
                            onChange={(event) =>
                              setDraft({
                                ...draft,
                                sequence_plan: {
                                  items: draft.sequence_plan.items.map(
                                    (entry) =>
                                      entry.key === item.key
                                        ? {
                                            ...entry,
                                            summary: event.target.value,
                                          }
                                        : entry,
                                  ),
                                },
                              })
                            }
                          />
                        </label>
                      </>
                    ) : (
                      <>
                        <strong>
                          {item.order_index}. {item.title}
                        </strong>
                        <span>
                          {roleLabels[item.narrative_role] ??
                            item.narrative_role}
                        </span>
                        <p>{item.summary}</p>
                      </>
                    )}
                  </li>
                ),
              )}
            </ol>
          </section>
        )}
        {draft && (
          <>
            <ErrorNotice error={save.error} />
            <div className="script-editor-actions">
              <Button
                variant="outline"
                type="button"
                className="button secondary"
                disabled={save.isPending}
                onClick={() => {
                  setDraft(null);
                  save.reset();
                }}
              >
                <X size={16} /> 取消
              </Button>
              <Button
                variant="default"
                className="button primary"
                disabled={save.isPending}
                onClick={() => save.mutate(draft)}
              >
                <Save size={16} /> {save.isPending ? "正在保存" : "保存规划"}
              </Button>
            </div>
          </>
        )}
      </div>
    </details>
  );
}
