import { useEffect, useRef, useState } from "react";
import {
  Button,
  Image,
  Picker,
  Text,
  Textarea,
  View,
} from "@tarojs/components";
import Taro, { getCurrentInstance } from "@tarojs/taro";
import type { Book, ProductionRun, ScriptProject } from "@lifereel/contracts";
import { miniApi } from "../../shared/api";
import { newRequestId } from "../../shared/uuid";
import { PageFrame } from "../../shared/PageFrame";
import { Icon } from "../../shared/Icon";

const runLabels: Record<string, string> = {
  queued: "排队中",
  running: "生成中",
  completed: "已完成",
  failed: "生成失败",
  cancelled: "已取消",
  pending: "待处理",
};

export default function ProductionPage() {
  const params = getCurrentInstance().router?.params;
  const subjectId = params?.subjectId || "";
  const [tab, setTab] = useState(params?.tab === "script" ? "script" : "video");
  const [runs, setRuns] = useState<ProductionRun[]>([]);
  const [projects, setProjects] = useState<ScriptProject[]>([]);
  const [books, setBooks] = useState<Book[]>([]);
  const [selected, setSelected] = useState<ScriptProject | null>(null);
  const [sceneIndex, setSceneIndex] = useState(0);
  const [bookId, setBookId] = useState("");
  const [adapterOpen, setAdapterOpen] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const adaptationKey = useRef("");
  const book = books.find((item) => item.id === bookId);
  const scene = selected?.scenes[sceneIndex];
  const savedChapters =
    book?.chapters.filter((ch) => ch.current?.body.trim()) || [];
  const stale = savedChapters.some((ch) => ch.stale);
  const seconds = scene?.duration_seconds || 0;
  const visibleRuns = runs.filter((run) =>
    projects.some((project) => project.id === run.project_id),
  );

  function choose(project: ScriptProject) {
    setSelected(project);
    setSceneIndex(0);
  }
  useEffect(() => {
    let active = true;
    Promise.all([miniApi.productionRuns(), miniApi.scripts(), miniApi.books()])
      .then(([items, scripts, manuscripts]) => {
        if (!active) return;
        const ownScripts = scripts.filter(
          (s) => !subjectId || s.subject_id === subjectId,
        );
        const ownBooks = manuscripts.filter(
          (b) => !subjectId || b.subject_id === subjectId,
        );
        setRuns(items);
        setProjects(ownScripts);
        setBooks(ownBooks);
        setBookId(ownBooks[0]?.id || "");
        if (ownScripts[0]) choose(ownScripts[0]);
        setReady(true);
      })
      .catch((e) => {
        if (active) {
          setError(e.message);
          setReady(true);
        }
      });
    return () => {
      active = false;
    };
  }, [subjectId]);

  async function adapt() {
    if (!book || !savedChapters.length || stale || loading) return;
    setLoading(true);
    setError("");
    adaptationKey.current ||= newRequestId();
    try {
      const project = await miniApi.generateScript({
        subject_id: book.subject_id,
        book_id: book.id,
        mode: "multi_chapter",
        audience: "family",
        idempotency_key: adaptationKey.current,
        adaptation_instructions: instructions.trim() || undefined,
      });
      choose(project);
      setProjects((p) => [project, ...p.filter((s) => s.id !== project.id)]);
      adaptationKey.current = "";
      setAdapterOpen(false);
      setInstructions("");
      setTab("script");
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "改编未完成，请核对来源及任务状态",
      );
    } finally {
      setLoading(false);
    }
  }
  async function start() {
    if (
      !selected ||
      !scene ||
      selected.source_stale ||
      selected.source_type !== "book" ||
      loading
    )
      return;
    const confirmation = await Taro.showModal({
      title: "生成人生影像",
      content: `“${scene.heading}”预计 ${seconds} 秒，按 0.80 元/秒计算约 ${(seconds * 0.8).toFixed(2)} 元。是否开始？`,
      confirmText: "开始生成",
    });
    if (!confirmation.confirm) return;
    setLoading(true);
    setError("");
    try {
      const run = await miniApi.startProduction({
        project_id: selected.id,
        scene_id: scene.id,
        audience: "family",
      });
      setRuns((p) => [run, ...p]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "视频任务创建失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <PageFrame
      title="人生影像"
      subtitle="让书里的故事，有了画面。"
      active="production"
      subjectId={subjectId || selected?.subject_id || book?.subject_id}
      locked={loading || !!instructions.trim()}
    >
      {error && <Text className="error">{error}</Text>}
      <View className="adapter-heading">
        <Icon name="book" />
        <Text className="section-title">从书稿生成剧本与分镜</Text>
        <Button
          className="icon-button"
          aria-label={adapterOpen ? "收起改编选项" : "展开改编选项"}
          disabled={loading}
          onClick={() => setAdapterOpen(!adapterOpen)}
        >
          <Icon name={adapterOpen ? "back" : "down"} />
        </Button>
      </View>
      {adapterOpen && (
        <View className="adapter-body">
          {books.length ? (
            <>
              <Picker
                range={books.map((b) => b.title)}
                value={Math.max(
                  0,
                  books.findIndex((b) => b.id === bookId),
                )}
                disabled={loading}
                onChange={(e) => {
                  setBookId(books[Number(e.detail.value)].id);
                  adaptationKey.current = "";
                }}
              >
                <View className="select-row">
                  <Text>{book?.title || "选择书稿"}</Text>
                  <Icon name="down" />
                </View>
              </Picker>
              <Text className="hint">
                整书改编 · {savedChapters.length} 章已成稿
                {book && book.chapters.length > savedChapters.length
                  ? ` · ${book.chapters.length - savedChapters.length} 章尚未成稿`
                  : ""}
              </Text>
              {stale && (
                <Text className="error">
                  书稿来源有更正，请更新正文后再改编。
                </Text>
              )}
              {!savedChapters.length && (
                <Text className="empty">这本书还没有已保存的正文</Text>
              )}
              <Textarea
                className="textarea"
                placeholder="改编偏好（可选）"
                value={instructions}
                disabled={loading}
                maxlength={4000}
                onInput={(e) => {
                  setInstructions(e.detail.value);
                  adaptationKey.current = "";
                }}
              />
              <Button
                className="primary-button"
                disabled={loading || !savedChapters.length || stale}
                loading={loading}
                onClick={adapt}
              >
                <Icon name="film" tone="white" />
                生成整书剧本与分镜
              </Button>
              <Button
                className="text-button"
                disabled={loading}
                onClick={() => {
                  setInstructions("");
                  setAdapterOpen(false);
                  adaptationKey.current = "";
                }}
              >
                取消
              </Button>
            </>
          ) : (
            <Text className="empty">还没有书稿</Text>
          )}
          <Button
            className="text-button"
            disabled={loading || !!instructions.trim() || !subjectId}
            onClick={() =>
              Taro.navigateTo({
                url: `/pages/books/index?subjectId=${encodeURIComponent(subjectId)}`,
              })
            }
          >
            前往写书
            <Icon name="arrow" />
          </Button>
        </View>
      )}
      <View className="segmented-control">
        <Button
          className={`segment-button ${tab === "video" ? "is-active" : ""}`}
          onClick={() => setTab("video")}
        >
          <Icon name="film" tone={tab === "video" ? "green" : "muted"} />
          影像作品
        </Button>
        <Button
          className={`segment-button ${tab === "script" ? "is-active" : ""}`}
          onClick={() => setTab("script")}
        >
          <Icon name="book" tone={tab === "script" ? "green" : "muted"} />
          剧本与分镜
        </Button>
      </View>
      {!ready ? (
        <Text className="empty">正在读取影像资料……</Text>
      ) : (
        <>
          {projects.length > 0 && (
            <Picker
              disabled={loading}
              range={projects.map(
                (p) => `${p.title} · 第${p.version_number}版`,
              )}
              value={Math.max(
                0,
                projects.findIndex((p) => p.id === selected?.id),
              )}
              onChange={(e) => choose(projects[Number(e.detail.value)])}
            >
              <View className="select-row">
                <Text>{selected?.title || "选择剧本"}</Text>
                <Icon name="down" />
              </View>
            </Picker>
          )}
          {selected?.source_stale && (
            <Text className="error">
              书稿来源已有更正，请更新书稿并重新改编。
            </Text>
          )}
          {selected && selected.scenes.length > 0 && (
            <View className="scene-picker">
              <Picker
                range={selected.scenes.map(
                  (s, i) => `场景 ${i + 1} · ${s.heading}`,
                )}
                value={sceneIndex}
                disabled={loading}
                onChange={(e) => setSceneIndex(Number(e.detail.value))}
              >
                <View className="select-row">
                  <Text>
                    场景 {sceneIndex + 1} / {selected.scenes.length} ·{" "}
                    {scene?.heading}
                  </Text>
                  <Icon name="down" />
                </View>
              </Picker>
            </View>
          )}
          {tab === "script" ? (
            <>
              {selected && selected.scenes.length > 0 ? (
                <>
                  {scene && (
                    <View className="section">
                      <Text className="section-title">{scene.heading}</Text>
                      {scene.plot && (
                        <View className="script-section">
                          <Text className="label">剧情</Text>
                          <Text className="list-meta">{scene.plot}</Text>
                        </View>
                      )}
                      {scene.narration && (
                        <View className="script-section">
                          <Text className="label">旁白</Text>
                          <Text className="list-meta">{scene.narration}</Text>
                        </View>
                      )}
                      {scene.dialogues?.map((d, i) => (
                        <View className="script-section" key={i}>
                          <Text className="label">
                            {d.kind === "narration" ? "旁白" : d.speaker}
                          </Text>
                          <Text className="list-meta">{d.text}</Text>
                        </View>
                      ))}
                      <Text className="label">画面</Text>
                      <Text className="list-meta">{scene.visual_prompt}</Text>
                      {(scene.shots || []).map((shot, i) => (
                        <View className="shot-card" key={shot.id}>
                          <Text className="caption">
                            镜头 {i + 1} · {shot.shot_type}
                          </Text>
                          <Text className="list-meta">
                            {shot.visual_prompt}
                          </Text>
                        </View>
                      ))}
                    </View>
                  )}
                </>
              ) : (
                <Text className="empty">暂时没有剧本与分镜</Text>
              )}
            </>
          ) : (
            <>
              {!visibleRuns.length && (
                <View className="empty-state">
                  <Image
                    src={require("../../assets/studio.png")}
                    className="empty-illustration"
                    mode="aspectFit"
                  />
                  <Text className="section-title">故事，等待开场</Text>
                  <Text className="hint">还没有生成的影像作品</Text>
                </View>
              )}
              {selected && (
                <View className="section">
                  <Text className="hint">
                    当前场景 · 预计 {seconds} 秒 · 0.80 元/秒
                  </Text>
                  <Button
                    className="primary-button"
                    disabled={
                      loading ||
                      !seconds ||
                      selected.source_stale ||
                      selected.source_type !== "book"
                    }
                    loading={loading}
                    onClick={start}
                  >
                    <Icon name="film" tone="white" />
                    生成当前场景影像
                  </Button>
                  {selected.source_type !== "book" && (
                    <Text className="hint">
                      该剧本来自早期资料，请从已保存书稿重新改编。
                    </Text>
                  )}
                </View>
              )}
              <View className="section-heading">
                <Text className="section-title">视频任务</Text>
                <Button
                  className="icon-button"
                  aria-label="刷新视频任务"
                  disabled={loading}
                  onClick={() =>
                    miniApi
                      .productionRuns()
                      .then(setRuns)
                      .catch((e) => setError(e.message))
                  }
                >
                  <Icon name="refresh" />
                </Button>
              </View>
              {visibleRuns.map((run) => (
                <View className="list-card" key={run.id}>
                  <View className="field-heading">
                    <Text className="list-title">
                      {projects.find((p) => p.id === run.project_id)?.title}
                    </Text>
                    <Text
                      className={`badge ${run.status === "completed" ? "" : "waiting"}`}
                    >
                      {runLabels[run.status] || run.status}
                    </Text>
                  </View>
                  <Text className="caption">
                    {new Date(run.created_at).toLocaleString()}
                  </Text>
                  {run.error_message && (
                    <Text className="error">{run.error_message}</Text>
                  )}
                  {run.output_manifest?.segments && (
                    <Text className="hint">
                      已完成{" "}
                      {
                        run.output_manifest.segments.filter(
                          (s) => s.status === "completed",
                        ).length
                      }{" "}
                      / {run.output_manifest.segments.length} 个镜头
                    </Text>
                  )}
                </View>
              ))}
            </>
          )}
        </>
      )}
    </PageFrame>
  );
}
