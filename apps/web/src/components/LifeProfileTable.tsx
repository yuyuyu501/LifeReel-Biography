import type {
  LifeProfile,
  ProfileEntry,
  ProfileField,
  ProfileChange,
  ProfileState,
  ProfileUse,
  ProfileCertainty,
  ProfileValue,
} from "@lifereel/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  ChevronDown,
  Download,
  History,
  Info,
  LockKeyhole,
  MessageSquare,
  Pencil,
  Plus,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { profilesApi } from "../api/profiles";
import { ErrorNotice } from "./QueryState";
import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
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
const certaintyNames: Record<ProfileCertainty, string> = {
  reported: "明确陈述",
  confirmed: "已确认",
  uncertain: "记不清",
  disputed: "待澄清",
  pending: "待整理",
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
  const [includePrivate, setIncludePrivate] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [filter, setFilter] = useState<"all" | "empty" | "pending">("all");
  const [category, setCategory] = useState("all");
  const [expandedEntries, setExpandedEntries] = useState<string[]>([]);
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
    mutationFn: () =>
      profilesApi.patch(
        profile.id,
        draft!.version,
        [draft!.change],
        draft!.request,
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
        value: entry?.value || (field.key.endsWith("[]") ? {} : ""),
        state: entry?.state || "filled",
        certainty:
          entry?.certainty === "pending"
            ? "reported"
            : entry?.certainty || "reported",
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
  const needsConfirmation = (entry: ProfileEntry) =>
    entry.state === "filled" &&
    ["uncertain", "disputed", "pending"].includes(entry.certainty);
  const emptyCount = profile.fields.filter(
    (field) => recordsFor(field).length === 0,
  ).length;
  const pendingCount = profile.fields.filter((field) =>
    recordsFor(field).some(needsConfirmation),
  ).length;
  const visibleFields = profile.fields.filter((field) => {
    if (category !== "all" && field.section !== category) return false;
    const records = recordsFor(field);
    return filter === "empty"
      ? records.length === 0
      : filter === "pending"
        ? records.some(needsConfirmation)
        : true;
  });
  const progress = profile.readiness.total_fields
    ? Math.min(
        100,
        (profile.readiness.processed_fields / profile.readiness.total_fields) *
          100,
      )
    : 0;
  return (
    <div className="life-profile-table">
      <header className="profile-summary">
        {heading && <h2>人生资料表</h2>}
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
              ["pending", "待确认", pendingCount],
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
                <a
                  href={profilesApi.exportUrl(
                    profile.id,
                    "xlsx",
                    includePrivate,
                  )}
                >
                  <Download size={15} aria-hidden="true" /> 下载表格
                </a>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <a
                  href={profilesApi.exportUrl(profile.id, "md", includePrivate)}
                >
                  <Download size={15} aria-hidden="true" /> 下载 Markdown
                </a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuCheckboxItem
                checked={includePrivate}
                onCheckedChange={setIncludePrivate}
                onSelect={(event) => event.preventDefault()}
              >
                包含内部资料
              </DropdownMenuCheckboxItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <div className="profile-category-row">
        <select
          aria-label="资料分类"
          value={category}
          disabled={!!draft}
          onChange={(event) => setCategory(event.target.value)}
        >
          <option value="all">全部分类</option>
          {profile.sections.map((section) => (
            <option key={section.key} value={section.key}>
              {section.title}
            </option>
          ))}
        </select>
        <span>{visibleFields.length} 项资料</span>
      </div>
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
      {draft && (
        <form
          className="profile-editor"
          ref={editor}
          aria-label={`编辑${draft.field.label}`}
          onSubmit={(e) => {
            e.preventDefault();
            if (!save.isPending) save.mutate();
          }}
        >
          <h3>
            {draft.entry ? "编辑" : "补充"} · {draft.field.label}
          </h3>
          {structuredEvent ? (
            [
              ...eventFields,
              ...Object.keys(draft.change.value as Record<string, unknown>)
                .filter((k) => !eventFields.some((f) => f[0] === k))
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
                  (draft.change.value as Record<string, unknown>).asset_id ||
                    "",
                )}
                onChange={(e) => {
                  const asset = assets.data?.find(
                    (a) => a.id === e.target.value,
                  );
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
                    (draft.change.value as Record<string, unknown>)
                      .description || "",
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
            <fieldset>
              <legend>想写哪些内容</legend>
              <p>不选择时继续整理整个人生；可以先选一部分写书。</p>
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
              当前内容
              <Textarea
                value={display(draft.change.value)}
                onChange={(e) => change({ value: e.target.value })}
              />
            </label>
          )}
          <div className="profile-editor-options">
            <label>
              处理状态
              <select
                value={draft.change.state}
                onChange={(e) =>
                  change({ state: e.target.value as ProfileState })
                }
              >
                {Object.entries(profileStates).map(([key, name]) => (
                  <option key={key} value={key}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              确定性
              <select
                value={draft.change.certainty}
                onChange={(e) =>
                  change({ certainty: e.target.value as ProfileCertainty })
                }
              >
                {Object.entries(certaintyNames).map(([key, name]) => (
                  <option key={key} value={key}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              使用范围
              <select
                value={draft.change.use_scope}
                onChange={(e) =>
                  change({ use_scope: e.target.value as ProfileUse })
                }
              >
                <option value="works">可用于书稿和影像</option>
                <option value="internal">只保留内部资料</option>
                <option value="pseudonym">使用化名</option>
              </select>
            </label>
          </div>
          {draft.version !== profile.version_number && (
            <p role="alert">
              资料已有新版本。您的草稿保留，请核对最新内容后再保存。
            </p>
          )}
          <ErrorNotice error={save.error} />
          {draft.change.use_scope === "pseudonym" && (
            <fieldset>
              <legend>化名替换</legend>
              <p>作品和默认导出使用化名，资料表保留原始称呼。</p>
              <Textarea
                placeholder="每行一组，例如：真实称呼=书中化名"
                defaultValue={Object.entries(draft.change.pseudonyms || {})
                  .map(([a, b]) => `${a}=${b}`)
                  .join("\n")}
                onChange={(e) =>
                  change({
                    pseudonyms: Object.fromEntries(
                      e.target.value
                        .split("\n")
                        .filter((line) => line.includes("="))
                        .map((line) => {
                          const pos = line.indexOf("=");
                          return [line.slice(0, pos), line.slice(pos + 1)];
                        }),
                    ),
                  })
                }
              />
            </fieldset>
          )}
          {draft.entry && (
            <label className="profile-editor-check">
              <input
                type="checkbox"
                checked={!!draft.change.delete}
                onChange={(e) => change({ delete: e.target.checked })}
              />
              移除此条资料，保留修改历史
            </label>
          )}
          <div className="profile-editor-buttons">
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? "保存中……" : "保存资料"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDraft(null)}
              disabled={save.isPending}
            >
              取消
            </Button>
            {draft.version !== profile.version_number && (
              <Button
                type="button"
                variant="outline"
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
      )}
      {visibleFields.length === 0 && (
        <p className="profile-filter-empty" role="status">
          {filter === "pending"
            ? "此分类没有待确认的资料"
            : "此分类没有待补充的资料"}
        </p>
      )}
      {profile.sections
        .filter((section) =>
          visibleFields.some((field) => field.section === section.key),
        )
        .map((section) => (
          <details
            key={`${section.key}-${filter}-${category}`}
            className="profile-section"
            open={section.key === "A" || filter !== "all" || category !== "all"}
          >
            <summary>
              <ChevronDown size={15} aria-hidden="true" />
              <strong>{section.title}</strong>
              <span>
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
            </summary>
            {visibleFields
              .filter((f) => f.section === section.key)
              .map((field) => {
                const records = recordsFor(field).filter(
                  (entry) => filter !== "pending" || needsConfirmation(entry),
                );
                return (
                  <div className="profile-field" key={field.key}>
                    <header>
                      <strong title={field.priority}>{field.label}</strong>
                    </header>
                    {(records.length ? records : [undefined]).map(
                      (entry, i) => {
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
                              {entry &&
                                (needsConfirmation(entry) ||
                                  entry.use_scope !== "works") && (
                                  <div className="profile-record-flags">
                                    {needsConfirmation(entry) && (
                                      <span className="profile-pending-flag">
                                        {certaintyNames[entry.certainty]}
                                      </span>
                                    )}
                                    {entry.use_scope !== "works" && (
                                      <span>
                                        <LockKeyhole
                                          size={12}
                                          aria-hidden="true"
                                        />
                                        {entry.use_scope === "internal"
                                          ? "内部资料"
                                          : "使用化名"}
                                      </span>
                                    )}
                                  </div>
                                )}
                            </div>
                            <div className="profile-field-actions">
                              {entry && (
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  title="来源与权限"
                                  aria-label={`查看${field.label}的来源与权限`}
                                  aria-expanded={expandedEntries.includes(
                                    entry.id,
                                  )}
                                  aria-controls={`profile-entry-${entry.id}`}
                                  onClick={() =>
                                    setExpandedEntries((current) =>
                                      current.includes(entry.id)
                                        ? current.filter(
                                            (id) => id !== entry.id,
                                          )
                                        : [...current, entry.id],
                                    )
                                  }
                                >
                                  <Info size={15} />
                                </Button>
                              )}
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                title={entry ? "编辑资料" : "填写"}
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
                                  aria-label="在聊天中补充"
                                  disabled={busy || !!draft}
                                  onClick={() => onTalk(field)}
                                >
                                  <MessageSquare size={15} />
                                </Button>
                              )}
                            </div>
                            {entry && expandedEntries.includes(entry.id) && (
                              <dl
                                className="profile-record-metadata"
                                id={`profile-entry-${entry.id}`}
                              >
                                <div>
                                  <dt>状态</dt>
                                  <dd>
                                    {profileStates[entry.state]} ·{" "}
                                    {certaintyNames[entry.certainty]}
                                  </dd>
                                </div>
                                <div>
                                  <dt>使用范围</dt>
                                  <dd>
                                    {entry.use_scope === "internal"
                                      ? "只用于内部资料"
                                      : entry.use_scope === "pseudonym"
                                        ? "使用化名"
                                        : "可用于书稿和影像"}
                                  </dd>
                                </div>
                                <div>
                                  <dt>来源</dt>
                                  <dd>
                                    {entry.source.type === "manual"
                                      ? "手动填写"
                                      : entry.source.type === "person"
                                        ? "人物档案"
                                        : entry.source.type === "legacy_claim"
                                          ? "历史采访"
                                          : "采访证据"}
                                  </dd>
                                </div>
                                {entry.source.quote && (
                                  <div>
                                    <dt>原文</dt>
                                    <dd>{entry.source.quote}</dd>
                                  </div>
                                )}
                              </dl>
                            )}
                          </div>
                        );
                      },
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
        ))}
    </div>
  );
}
