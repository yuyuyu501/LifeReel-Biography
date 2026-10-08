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
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { profilesApi } from "../api/profiles";
import { ErrorNotice } from "./QueryState";
import { Button } from "./ui/button";
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
  onTalk,
}: {
  profile: LifeProfile;
  busy?: boolean;
  onTalk?: (field: ProfileField) => void;
}) {
  const cache = useQueryClient();
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
  return (
    <div className="life-profile-table">
      <header className="profile-summary">
        <span className="eyebrow">
          人生资料 · 第 {profile.version_number} 版
        </span>
        <h2>人生资料表</h2>
        <p>
          {profile.readiness.processed_fields} /{" "}
          {profile.readiness.total_fields} 项已处理
        </p>
        <p role="status">{profile.readiness.message}</p>
        {profile.readiness.themes.length > 0 && (
          <ul>
            {profile.readiness.themes.map((theme) => (
              <li key={theme.section}>
                {theme.title}：{theme.reason}
              </li>
            ))}
          </ul>
        )}
        <Link
          to={`/books?subject=${profile.subject_id}`}
          className="profile-next"
        >
          前往写书
        </Link>
        <small>
          可以只写已有的经历，其他内容以后继续。已处理数量不代表素材充足。
        </small>
      </header>
      <div className="profile-export">
        <a href={profilesApi.exportUrl(profile.id, "xlsx", includePrivate)}>
          下载表格
        </a>
        <a href={profilesApi.exportUrl(profile.id, "md", includePrivate)}>
          下载 Markdown
        </a>
        <label>
          <input
            type="checkbox"
            checked={includePrivate}
            onChange={(e) => setIncludePrivate(e.target.checked)}
          />
          包含内部资料
        </label>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowHistory(!showHistory)}
        >
          修改历史
        </Button>
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
            <label>
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
      {profile.sections.map((section) => (
        <details
          key={section.key}
          className="profile-section"
          open={section.key === "A"}
        >
          <summary>
            {section.title}
            <span>
              {
                profile.entries.filter(
                  (e) =>
                    e.state !== "empty" &&
                    profile.fields.find((f) => f.key === e.field_key)
                      ?.section === section.key,
                ).length
              }{" "}
              条资料
            </span>
          </summary>
          {profile.fields
            .filter((f) => f.section === section.key)
            .map((field) => {
              const records = profile.entries.filter(
                (e) => e.field_key === field.key && e.state !== "empty",
              );
              return (
                <div className="profile-field" key={field.key}>
                  <header>
                    <strong>{field.label}</strong>
                    <small>{field.priority}</small>
                  </header>
                  {(records.length ? records : [undefined]).map((entry, i) => (
                    <div key={entry?.id || i} className="profile-record">
                      <p>
                        {entry
                          ? display(entry.value) || profileStates[entry.state]
                          : "待补充"}
                      </p>
                      {entry && (
                        <small>
                          {profileStates[entry.state]} ·{" "}
                          {certaintyNames[entry.certainty]} ·{" "}
                          {entry.use_scope === "internal"
                            ? "只用于内部资料"
                            : entry.use_scope === "pseudonym"
                              ? "使用化名"
                              : "可用于作品"}
                          {entry.source.type &&
                            ` · 来源：${entry.source.type === "manual" ? "手动填写" : entry.source.type === "person" ? "人物档案" : entry.source.type === "legacy_claim" ? "历史采访" : "采访证据"}`}
                        </small>
                      )}
                      <div className="profile-field-actions">
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={!!draft}
                          onClick={() => begin(field, entry)}
                        >
                          {entry ? "编辑资料" : "填写"}
                        </Button>
                        {onTalk && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busy || !!draft}
                            onClick={() => onTalk(field)}
                          >
                            在聊天中补充
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                  {field.key.endsWith("[]") && records.length > 0 && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!!draft}
                      onClick={() => begin(field)}
                    >
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
