import { useEffect, useState } from "react";
import {
  Button,
  Input,
  Picker,
  Text,
  Textarea,
  View,
} from "@tarojs/components";
import Taro, { getCurrentInstance } from "@tarojs/taro";
import type {
  LifeProfile,
  ProfileChange,
  ProfileEntry,
  ProfileField,
  ProfileState,
} from "@lifereel/contracts";
import { miniApi } from "../../shared/api";
import { newRequestId } from "../../shared/uuid";
import { PreviewNotice } from "../../shared/PreviewNotice";

const states: ProfileState[] = [
  "filled",
  "unknown",
  "deferred",
  "declined",
  "not_applicable",
  "empty",
];
const stateNames = [
  "已有资料",
  "暂不清楚",
  "暂时跳过",
  "不愿回答",
  "不适用",
  "待补充",
];
const parts = [
  ["title", "经历名称"],
  ["time_raw", "大致时间"],
  ["place", "地点"],
  ["people", "人物与关系"],
  ["what", "发生了什么"],
  ["action", "您做了什么"],
  ["impact", "结果与影响"],
];
function content(value: unknown) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object")
    return Object.entries(value)
      .map(
        ([key, v]) =>
          `${parts.find((p) => p[0] === key)?.[1] || "补充信息"}：${String(v)}`,
      )
      .join("\n");
  return "";
}

export default function ProfilePage() {
  const subjectId = getCurrentInstance().router?.params.subjectId || "";
  const [profile, setProfile] = useState<LifeProfile | null>(null);
  const [section, setSection] = useState("A");
  const [draft, setDraft] = useState<{
    field: ProfileField;
    version: number;
    request: string;
    change: ProfileChange;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function load() {
    return miniApi.profile(subjectId).then(setProfile);
  }
  useEffect(() => {
    load().catch((e) => setError(String(e.message || e)));
  }, [subjectId]);
  function begin(field: ProfileField, entry?: ProfileEntry) {
    if (!profile) return;
    setError("");
    setDraft({
      field,
      version: profile.version_number,
      request: newRequestId(),
      change: {
        id: entry?.id,
        field_key: field.key,
        record_key:
          entry?.record_key ||
          (field.key.endsWith("[]") ? newRequestId() : "single"),
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
  function change(value: Partial<ProfileChange>) {
    setDraft(
      (d) =>
        d && {
          ...d,
          request: newRequestId(),
          change: { ...d.change, ...value },
        },
    );
  }
  async function save() {
    if (!profile || !draft) return;
    setBusy(true);
    setError("");
    try {
      setProfile(
        await miniApi.editProfile(
          profile.id,
          draft.version,
          [draft.change],
          draft.request,
        ),
      );
      setDraft(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败，草稿已保留");
    } finally {
      setBusy(false);
    }
  }
  return (
    <View className="page">
      <PreviewNotice />
      <Text className="title">人生资料表</Text>
      {error && <Text className="error">{error}</Text>}
      {profile && (
        <>
          <View className="card">
            <Text>
              资料第 {profile.version_number} 版 ·{" "}
              {profile.readiness.processed_fields} / 67 项已处理
            </Text>
            <Text className="hint">{profile.readiness.message}</Text>
            <Text className="hint">
              已处理数量不代表素材充足，可以分多次补充。
            </Text>
            <View className="action-row">
              <Button
                onClick={() =>
                  Taro.navigateTo({
                    url: `/pages/interview/index?subjectId=${subjectId}`,
                  })
                }
              >
                继续采访
              </Button>
              <Button
                onClick={() =>
                  Taro.navigateTo({
                    url: `/pages/books/index?subjectId=${subjectId}`,
                  })
                }
              >
                前往写书
              </Button>
              <Button
                onClick={() =>
                  miniApi
                    .downloadProfile(profile.id)
                    .catch((e) => setError(e.message))
                }
              >
                下载表格
              </Button>
            </View>
          </View>
          <View className="action-row">
            {profile.sections.map((s) => (
              <Button
                key={s.key}
                className={
                  section === s.key ? "primary-button" : "secondary-button"
                }
                onClick={() => setSection(s.key)}
              >
                {s.title}
              </Button>
            ))}
          </View>
          {draft ? (
            <View className="card">
              <Text className="section-title">编辑 · {draft.field.label}</Text>
              {draft.field.key !== "scope.coverage" &&
              typeof draft.change.value === "object" &&
              !Array.isArray(draft.change.value) ? (
                [
                  ...parts,
                  ...Object.keys(draft.change.value as Record<string, unknown>)
                    .filter((k) => !parts.some((p) => p[0] === k))
                    .map((k) => [k, "补充说明"]),
                ].map(([key, label]) => (
                  <View key={key}>
                    <Text>{label}</Text>
                    <Textarea
                      className="textarea"
                      value={String(
                        (draft.change.value as Record<string, unknown>)[key] ||
                          "",
                      )}
                      onInput={(e) =>
                        change({
                          value: {
                            ...(draft.change.value as Record<string, unknown>),
                            [key]: e.detail.value,
                          },
                        })
                      }
                    />
                  </View>
                ))
              ) : draft.field.key === "scope.coverage" ? (
                <View>
                  <Text>想写哪些内容（可多选，留空为整个人生）</Text>
                  {profile.sections
                    .filter((s) => !["A", "L"].includes(s.key))
                    .map((s) => {
                      const selected =
                        typeof draft.change.value === "object" &&
                        !Array.isArray(draft.change.value)
                          ? ((draft.change.value.sections || []) as string[])
                          : [];
                      return (
                        <Button
                          key={s.key}
                          className={
                            selected.includes(s.key)
                              ? "primary-button"
                              : "secondary-button"
                          }
                          onClick={() =>
                            change({
                              value: {
                                sections: selected.includes(s.key)
                                  ? selected.filter((k) => k !== s.key)
                                  : [...selected, s.key],
                              },
                            })
                          }
                        >
                          {s.title}
                        </Button>
                      );
                    })}
                </View>
              ) : (
                <Textarea
                  className="textarea"
                  value={content(draft.change.value)}
                  onInput={(e) => change({ value: e.detail.value })}
                />
              )}
              <Picker
                range={stateNames}
                value={states.indexOf(draft.change.state)}
                onChange={(e) =>
                  change({ state: states[Number(e.detail.value)] })
                }
              >
                <View className="select-row">
                  处理状态：{stateNames[states.indexOf(draft.change.state)]}
                </View>
              </Picker>
              <Picker
                range={["可用于作品", "只保留内部资料", "使用化名"]}
                value={["works", "internal", "pseudonym"].indexOf(
                  draft.change.use_scope,
                )}
                onChange={(e) =>
                  change({
                    use_scope: ["works", "internal", "pseudonym"][
                      Number(e.detail.value)
                    ] as ProfileChange["use_scope"],
                  })
                }
              >
                <View className="select-row">
                  使用范围：
                  {draft.change.use_scope === "internal"
                    ? "只保留内部资料"
                    : draft.change.use_scope === "pseudonym"
                      ? "使用化名"
                      : "可用于作品"}
                </View>
              </Picker>
              {draft.change.use_scope === "pseudonym" && (
                <View>
                  <Text>原称呼与化名</Text>
                  <Input
                    className="input"
                    placeholder="原称呼=书中化名"
                    onInput={(e) => {
                      const pos = e.detail.value.indexOf("=");
                      if (pos > 0)
                        change({
                          pseudonyms: {
                            [e.detail.value.slice(0, pos)]:
                              e.detail.value.slice(pos + 1),
                          },
                        });
                    }}
                  />
                </View>
              )}
              <View className="action-row">
                <Button disabled={busy} onClick={save}>
                  保存资料
                </Button>
                <Button disabled={busy} onClick={() => setDraft(null)}>
                  取消
                </Button>
              </View>
            </View>
          ) : (
            profile.fields
              .filter((f) => f.section === section)
              .map((field) => {
                const records = profile.entries.filter(
                  (e) => e.field_key === field.key && e.state !== "empty",
                );
                return (
                  <View className="card" key={field.key}>
                    <Text className="section-title">{field.label}</Text>
                    <Text className="hint">{field.priority}</Text>
                    {records.map((entry) => (
                      <View key={entry.id}>
                        <Text className="list-meta">
                          {content(entry.value)}
                        </Text>
                        <Text className="hint">
                          {stateNames[states.indexOf(entry.state)]} ·{" "}
                          {entry.use_scope === "internal"
                            ? "内部资料"
                            : "作品资料"}
                        </Text>
                        <Button
                          className="text-button"
                          onClick={() => begin(field, entry)}
                        >
                          编辑资料
                        </Button>
                      </View>
                    ))}
                    {!records.length && <Text className="hint">待补充</Text>}
                    {(!records.length || field.key.endsWith("[]")) && (
                      <Button
                        className="secondary-button"
                        onClick={() => begin(field)}
                      >
                        {records.length ? "添加一条" : "填写"}
                      </Button>
                    )}
                  </View>
                );
              })
          )}
        </>
      )}
    </View>
  );
}
