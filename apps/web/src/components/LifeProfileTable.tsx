import type {
  LifeProfile,
  ProfileEntry,
  ProfileField,
  ProfileChange,
  ProfileState,
  ProfileValue,
} from "@lifereel/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  BriefcaseBusiness,
  ChevronDown,
  ClipboardList,
  Download,
  FileText,
  Files,
  GraduationCap,
  Heart,
  History,
  House,
  Leaf,
  ListFilter,
  MessagesSquare,
  MessageSquare,
  Pencil,
  Plus,
  Signpost,
  Star,
  Trash2,
  UserRound,
  UsersRound,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { profilesApi } from "../api/profiles";
import { ErrorNotice } from "./QueryState";
import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { Textarea } from "./ui/textarea";

const profileStates: Record<ProfileState, string> = {
  empty: "待补充",
  filled: "已有资料",
  unknown: "暂不清楚",
  deferred: "暂时跳过",
  declined: "不愿回答",
  not_applicable: "不适用",
};
const eventFields = [
  ["title", "经历名称"],
  ["time_raw", "时间（大概也可以）"],
  ["place", "地点"],
  ["people", "相关人物与关系"],
  ["what", "发生了什么"],
  ["action", "您做了什么"],
  ["feelings", "您当时的感受（可空）"],
  ["impact", "结果或后来的影响"],
] as const;
const sectionIcons: Record<string, LucideIcon> = {
  A: ClipboardList,
  B: House,
  C: UserRound,
  D: GraduationCap,
  E: BriefcaseBusiness,
  F: Heart,
  G: UsersRound,
  H: Signpost,
  I: Star,
  J: House,
  K: MessagesSquare,
  L: Files,
};
function display(value: ProfileValue): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(String).join("、");
  const labels: Record<string, string> = Object.fromEntries(eventFields);
  return Object.entries(value)
    .filter(
      ([key]) =>
        !["asset_id", "kind", "event_id", "source_asset_id"].includes(key),
    )
    .map(
      ([key, v]) =>
        `${labels[key] || ({ name: "名称", relationship: "关系", role: "角色", institution: "机构", description: "补充说明", sections: "记录范围", result: "结果" } as Record<string, string>)[key] || "补充信息"}：${Array.isArray(v) ? v.join("、") : String(v)}`,
    )
    .join("\n");
}

export function LifeProfileTable({
  profile,
  busy = false,
  heading = true,
  onTalk,
  onEditingChange,
}: {
  profile: LifeProfile;
  busy?: boolean;
  heading?: boolean;
  onTalk?: (field: ProfileField) => void;
  onEditingChange?: (editing: boolean) => void;
}) {
  const cache = useQueryClient();
  const editor = useRef<HTMLFormElement>(null);
  const assets = useQuery({
    queryKey: ["profile-assets", profile.subject_id],
    queryFn: () => api.listEvidence(profile.subject_id),
  });
  const [draft, setDraft] = useState<{
    field: ProfileField;
    entry?: ProfileEntry;
    change: ProfileChange;
    version: number;
    request: string;
  } | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [filter, setFilter] = useState<"all" | "empty">("all");
  const [category, setCategory] = useState("all");
  const [expandedValues, setExpandedValues] = useState<string[]>([]);
  const editingField = draft?.field.key;
  const editingEntry = draft?.entry?.id;
  const editing = Boolean(draft);
  useEffect(() => {
    onEditingChange?.(editing);
  }, [editing, onEditingChange]);
  useEffect(() => {
    if (!editingField) return;
    editor.current?.scrollIntoView?.({ block: "nearest" });
    editor.current
      ?.querySelector<HTMLElement>("textarea, select")
      ?.focus({ preventScroll: true });
  }, [editingField, editingEntry]);
  const history = useQuery({
    queryKey: ["profile-history", profile.id],
    queryFn: () => profilesApi.history(profile.id),
    enabled: showHistory,
  });
  const save = useMutation({
    mutationFn: (override?: ProfileChange) =>
      profilesApi.patch(
        profile.id,
        draft!.version,
        [override || draft!.change],
        override ? crypto.randomUUID() : draft!.request,
      ),
    onSuccess: async () => {
      setDraft(null);
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["interview-workspace"] }),
        cache.invalidateQueries({ queryKey: ["life-profile"] }),
        cache.invalidateQueries({ queryKey: ["profile-history", profile.id] }),
        cache.invalidateQueries({ queryKey: ["books"] }),
      ]);
    },
  });
  function begin(field: ProfileField, entry?: ProfileEntry) {
    save.reset();
    setDraft({
      field,
      entry,
      version: profile.version_number,
      request: crypto.randomUUID(),
      change: {
        id: entry?.id,
        field_key: field.key,
        record_key:
          entry?.record_key ||
          (field.key.endsWith("[]") ? crypto.randomUUID() : "single"),
        value:
          entry?.value ??
          (field.key.endsWith("events[]") || field.key === "materials.assets[]"
            ? {}
            : ""),
        state: "filled",
        certainty: "reported",
        use_scope: entry?.use_scope || "works",
        pseudonyms: entry?.pseudonyms || {},
      },
    });
  }
  function change(values: Partial<ProfileChange>) {
    setDraft(
      (current) =>
        current && {
          ...current,
          request: crypto.randomUUID(),
          change: { ...current.change, ...values },
        },
    );
    save.reset();
  }
  const structuredEvent =
    !!draft &&
    !["scope.coverage", "materials.assets[]"].includes(draft.field.key) &&
    !Array.isArray(draft.change.value) &&
    typeof draft.change.value === "object";
  const recordsFor = (field: ProfileField) =>
    profile.entries.filter(
      (entry) => entry.field_key === field.key && entry.state !== "empty",
    );
  const emptyCount = profile.fields.filter(
    (field) => recordsFor(field).length === 0,
  ).length;
  const visibleFields = profile.fields.filter((field) => {
    if (draft?.field.key === field.key) return true;
    if (category !== "all" && field.section !== category) return false;
    const records = recordsFor(field);
    return filter !== "empty" || records.length === 0;
  });
  const progress = profile.readiness.total_fields
    ? Math.min(
        100,
        (profile.readiness.processed_fields / profile.readiness.total_fields) *
          100,
      )
    : 0;
  const inlineEditor = draft && (
    <form
      className="profile-editor"
      ref={editor}
      aria-label={`编辑${draft.field.label}`}
      onSubmit={(e) => {
        e.preventDefault();
        if (!save.isPending && draft.version === profile.version_number)
          save.mutate();
      }}
    >
      <fieldset className="profile-editor-content" disabled={save.isPending}>
        {structuredEvent ? (
          [
            ...(draft.field.key.endsWith("events[]") ? eventFields : []),
            ...Object.keys(draft.change.value as Record<string, unknown>)
              .filter(
                (k) =>
                  !(
                    draft.field.key.endsWith("events[]") &&
                    eventFields.some((f) => f[0] === k)
                  ) &&
                  !["asset_id", "kind", "event_id", "source_asset_id"].includes(
                    k,
                  ),
              )
              .map(
                (k) =>
                  [
                    k,
                    (
                      {
                        name: "人物名称",
                        relationship: "关系",
                        institution: "学校或机构",
                        role: "角色",
                        skill: "技能",
                        result: "结果",
                        description: "补充说明",
                      } as Record<string, string>
                    )[k] || "补充内容",
                  ] as const,
              ),
          ].map(([key, label]) => (
            <label key={key}>
              {label}
              <Textarea
                value={String(
                  (draft.change.value as Record<string, unknown>)[key] || "",
                )}
                onChange={(e) =>
                  change({
                    value: {
                      ...(draft.change.value as Record<string, unknown>),
                      [key]: Array.isArray(
                        (draft.change.value as Record<string, unknown>)[key],
                      )
                        ? e.target.value.split(/[、,，]/).filter(Boolean)
                        : e.target.value,
                    },
                  })
                }
              />
            </label>
          ))
        ) : draft.field.key === "materials.assets[]" ? (
          <fieldset>
            <legend>关联已上传素材</legend>
            <select
              value={String(
                (draft.change.value as Record<string, unknown>).asset_id || "",
              )}
              onChange={(e) => {
                const asset = assets.data?.find((a) => a.id === e.target.value);
                if (asset)
                  change({
                    value: {
                      title: asset.original_filename,
                      asset_id: asset.id,
                      kind: asset.kind,
                    },
                  });
              }}
            >
              <option value="">请选择照片、录音或文档</option>
              {assets.data?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.original_filename}
                </option>
              ))}
            </select>
            <label>
              素材说明
              <Textarea
                value={String(
                  (draft.change.value as Record<string, unknown>).description ||
                    "",
                )}
                onChange={(e) =>
                  change({
                    value: {
                      ...(draft.change.value as Record<string, unknown>),
                      description: e.target.value,
                    },
                  })
                }
              />
            </label>
          </fieldset>
        ) : draft.field.key === "scope.coverage" ? (
          <fieldset className="profile-coverage-options">
            <legend>想写哪些内容</legend>
            {profile.sections
              .filter((s) => !["A", "L"].includes(s.key))
              .map((s) => {
                const selected =
                  typeof draft.change.value === "object" &&
                  !Array.isArray(draft.change.value)
                    ? ((draft.change.value.sections || []) as string[])
                    : [];
                return (
                  <label key={s.key}>
                    <input
                      type="checkbox"
                      checked={selected.includes(s.key)}
                      onChange={(e) =>
                        change({
                          value: {
                            sections: e.target.checked
                              ? [...selected, s.key]
                              : selected.filter((k) => k !== s.key),
                          },
                        })
                      }
                    />
                    {s.title}
                  </label>
                );
              })}
          </fieldset>
        ) : (
          <label>
            <span className="sr-only">当前内容</span>
            <Textarea
              value={display(draft.change.value)}
              onChange={(e) => change({ value: e.target.value })}
            />
          </label>
        )}
      </fieldset>
      {draft.version !== profile.version_number && (
        <p role="alert">
          资料已有新版本。您的草稿保留，请核对最新内容后再保存。
        </p>
      )}
      <ErrorNotice error={save.error} />
      <div className="profile-editor-buttons">
        <Button
          type="submit"
          size="sm"
          disabled={save.isPending || draft.version !== profile.version_number}
        >
          {save.isPending ? "保存中……" : "保存资料"}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setDraft(null)}
          disabled={save.isPending}
        >
          取消
        </Button>
        {draft.entry && (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="profile-remove-record"
            title="删除这条资料"
            aria-label="删除这条资料"
            disabled={
              save.isPending || draft.version !== profile.version_number
            }
            onClick={() => save.mutate({ ...draft.change, delete: true })}
          >
            <Trash2 size={15} />
          </Button>
        )}
        {draft.version !== profile.version_number && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              setDraft({
                ...draft,
                version: profile.version_number,
                request: crypto.randomUUID(),
              })
            }
          >
            已核对，按最新版本保存
          </Button>
        )}
      </div>
    </form>
  );
  return (
    <div className="life-profile-table">
      <header className="profile-summary">
        {heading && (
          <h2>
            <Leaf size={18} aria-hidden="true" />
            人生资料表
          </h2>
        )}
        <div className="profile-summary-topline">
          <div>
            <span className="profile-version">
              第 {profile.version_number} 版
            </span>
            <p className="profile-completion">
              <strong>{profile.readiness.processed_fields}</strong>
              <span>/ {profile.readiness.total_fields} 项已处理</span>
            </p>
          </div>
          <Link
            to={`/books?subject=${profile.subject_id}`}
            className="profile-book-link"
          >
            <BookOpen size={15} aria-hidden="true" />
            前往写书 <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </div>
        <div
          className="profile-completion-track"
          role="progressbar"
          aria-label="人生资料完成度"
          aria-valuemin={0}
          aria-valuemax={profile.readiness.total_fields || 1}
          aria-valuenow={profile.readiness.processed_fields}
        >
          <span style={{ width: `${progress}%` }} />
        </div>
        <p className="profile-readiness" role="status">
          {profile.readiness.message}
        </p>
        {profile.readiness.themes.length > 0 && (
          <details className="profile-themes">
            <summary>
              <ChevronDown size={14} aria-hidden="true" />
              {profile.readiness.themes.length} 个可写主题
            </summary>
            <ul>
              {profile.readiness.themes.map((theme) => (
                <li key={theme.section}>
                  {theme.title}：{theme.reason}
                </li>
              ))}
            </ul>
          </details>
        )}
      </header>
      <div className="profile-toolbar">
        <div className="profile-filters" role="group" aria-label="资料筛选">
          {(
            [
              ["all", "全部", profile.fields.length],
              ["empty", "待补充", emptyCount],
            ] as const
          ).map(([key, label, count]) => (
            <button
              type="button"
              key={key}
              aria-pressed={filter === key}
              disabled={!!draft}
              onClick={() => setFilter(key)}
            >
              {label}
              <span>{count}</span>
            </button>
          ))}
        </div>
        <div className="profile-tools">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                title="筛选分类"
                aria-label="筛选分类"
                aria-pressed={category !== "all"}
                disabled={!!draft}
              >
                <ListFilter size={16} />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>资料分类</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={category}
                onValueChange={setCategory}
              >
                <DropdownMenuRadioItem value="all">
                  全部分类
                </DropdownMenuRadioItem>
                {profile.sections.map((section) => (
                  <DropdownMenuRadioItem key={section.key} value={section.key}>
                    {section.title}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            variant="ghost"
            size="icon-sm"
            title="修改历史"
            aria-label="修改历史"
            aria-pressed={showHistory}
            onClick={() => setShowHistory(!showHistory)}
          >
            <History size={16} />
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                title="导出资料"
                aria-label="导出资料"
              >
                <Download size={16} />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem asChild>
                <a href={profilesApi.exportUrl(profile.id, "xlsx")}>
                  <Download size={15} aria-hidden="true" /> 下载表格
                </a>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <a href={profilesApi.exportUrl(profile.id, "md")}>
                  <Download size={15} aria-hidden="true" /> 下载 Markdown
                </a>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      {category !== "all" && (
        <div className="profile-category-row">
          <span>
            {
              profile.sections.find((section) => section.key === category)
                ?.title
            }{" "}
            · {visibleFields.length} 项资料
          </span>
          <Button
            variant="ghost"
            size="icon-xs"
            title="清除分类筛选"
            aria-label="清除分类筛选"
            disabled={!!draft}
            onClick={() => setCategory("all")}
          >
            <X size={12} />
          </Button>
        </div>
      )}
      {showHistory && (
        <div className="profile-history">
          <ErrorNotice error={history.error} />
          {history.data?.map((rev) => (
            <details key={rev.version_number}>
              <summary>
                第 {rev.version_number} 版 ·{" "}
                {rev.actor.startsWith("manual")
                  ? "人工修改"
                  : rev.actor === "ai"
                    ? "采访整理"
                    : "历史迁入"}
              </summary>
              {rev.changes
                .filter((c) => c.before || c.after)
                .map((c, i) => {
                  const before = c.before as ProfileEntry | null;
                  const after = c.after as ProfileEntry | null;
                  const field = profile.fields.find(
                    (f) => f.key === (after?.field_key || before?.field_key),
                  );
                  return (
                    <p key={i}>
                      <strong>{field?.label || "资料"}</strong>
                      <br />
                      原内容：{before ? display(before.value) : "未填写"}
                      <br />
                      新内容：{after ? display(after.value) : "已移除"}
                    </p>
                  );
                })}
            </details>
          ))}
        </div>
      )}
      {visibleFields.length === 0 && (
        <p className="profile-filter-empty" role="status">
          此分类没有待补充的资料
        </p>
      )}
      {profile.sections
        .filter((section) =>
          visibleFields.some((field) => field.section === section.key),
        )
        .map((section) => {
          const SectionIcon = sectionIcons[section.key] || FileText;
          return (
            <details
              key={`${section.key}-${filter}-${category}`}
              className="profile-section"
              open={
                section.key === "A" || filter !== "all" || category !== "all"
              }
            >
              <summary>
                <span className="profile-section-icon">
                  <SectionIcon size={16} aria-hidden="true" />
                </span>
                <strong>{section.title}</strong>
                <span className="profile-section-count">
                  {
                    profile.fields.filter(
                      (field) =>
                        field.section === section.key &&
                        recordsFor(field).length > 0,
                    ).length
                  }
                  /
                  {
                    profile.fields.filter(
                      (field) => field.section === section.key,
                    ).length
                  }
                </span>
                <ChevronDown size={15} aria-hidden="true" />
              </summary>
              {visibleFields
                .filter((f) => f.section === section.key)
                .map((field) => {
                  const records = recordsFor(field);
                  return (
                    <div className="profile-field" key={field.key}>
                      <header>
                        <strong>{field.label}</strong>
                      </header>
                      {(records.length ? records : [undefined]).map(
                        (entry, i) => {
                          if (
                            draft?.field.key === field.key &&
                            draft.entry?.id === entry?.id
                          ) {
                            return (
                              <div
                                className="profile-record is-editing"
                                key={entry?.id || i}
                              >
                                {inlineEditor}
                              </div>
                            );
                          }
                          const content = entry
                            ? display(entry.value) || profileStates[entry.state]
                            : "待补充";
                          const longContent =
                            content.length > 140 ||
                            content.split("\n").length > 3;
                          const valueExpanded =
                            !!entry && expandedValues.includes(entry.id);
                          return (
                            <div
                              key={entry?.id || i}
                              className={`profile-record${entry ? "" : " is-empty"}`}
                            >
                              <div className="profile-record-body">
                                <p
                                  className={
                                    longContent && !valueExpanded
                                      ? "profile-value-preview"
                                      : undefined
                                  }
                                >
                                  {content}
                                </p>
                                {entry && longContent && (
                                  <button
                                    className="profile-value-toggle"
                                    type="button"
                                    aria-expanded={valueExpanded}
                                    onClick={() =>
                                      setExpandedValues((current) =>
                                        valueExpanded
                                          ? current.filter(
                                              (id) => id !== entry.id,
                                            )
                                          : [...current, entry.id],
                                      )
                                    }
                                  >
                                    {valueExpanded ? "收起" : "展开内容"}
                                    <ChevronDown size={12} aria-hidden="true" />
                                  </button>
                                )}
                              </div>
                              <div className="profile-field-actions">
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  title={entry ? "编辑资料" : "填写"}
                                  className="size-7"
                                  aria-label={entry ? "编辑资料" : "填写"}
                                  disabled={!!draft}
                                  onClick={() => begin(field, entry)}
                                >
                                  {entry ? (
                                    <Pencil size={15} />
                                  ) : (
                                    <Plus size={15} />
                                  )}
                                </Button>
                                {onTalk && (
                                  <Button
                                    variant="ghost"
                                    size="icon-sm"
                                    title="在聊天中补充"
                                    className="size-7"
                                    aria-label="在聊天中补充"
                                    disabled={busy || !!draft}
                                    onClick={() => onTalk(field)}
                                  >
                                    <MessageSquare size={15} />
                                  </Button>
                                )}
                              </div>
                            </div>
                          );
                        },
                      )}
                      {draft?.field.key === field.key &&
                        !draft.entry &&
                        records.length > 0 && (
                          <div className="profile-record is-editing">
                            {inlineEditor}
                          </div>
                        )}
                      {field.key.endsWith("[]") && records.length > 0 && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="profile-add-record"
                          disabled={!!draft}
                          onClick={() => begin(field)}
                        >
                          <Plus size={14} aria-hidden="true" />
                          添加一条
                        </Button>
                      )}
                    </div>
                  );
                })}
            </details>
          );
        })}
    </div>
  );
}
