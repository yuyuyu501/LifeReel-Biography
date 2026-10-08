import { useEffect, useState } from "react";
import { Button, Text, View } from "@tarojs/components";
import Taro, { getCurrentInstance } from "@tarojs/taro";
import type { Book, ProductionRun, ScriptProject } from "@lifereel/contracts";
import { miniApi } from "../../shared/api";
import { newRequestId } from "../../shared/uuid";
import { PreviewNotice } from "../../shared/PreviewNotice";

export default function ProductionPage() {
  const subjectId = getCurrentInstance().router?.params?.subjectId || "";
  const [runs, setRuns] = useState<ProductionRun[]>([]);
  const [projects, setProjects] = useState<ScriptProject[]>([]);
  const [books, setBooks] = useState<Book[]>([]);
  const [selected, setSelected] = useState<ScriptProject | null>(null);
  const [sceneId, setSceneId] = useState("");
  const [revisions, setRevisions] = useState<string[]>([]);
  const [bookId, setBookId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  function choose(project: ScriptProject) {
    setSelected(project);
    setSceneId(project.scenes[0]?.id || "");
  }
  useEffect(() => {
    Promise.all([miniApi.productionRuns(), miniApi.scripts(), miniApi.books()])
      .then(([items, scripts, manuscripts]) => {
        setRuns(items);
        setProjects(
          subjectId
            ? scripts.filter((s) => s.subject_id === subjectId)
            : scripts,
        );
        setBooks(
          subjectId
            ? manuscripts.filter((b) => b.subject_id === subjectId)
            : manuscripts,
        );
        const first = scripts.find(
          (s) => !subjectId || s.subject_id === subjectId,
        );
        if (first) choose(first);
      })
      .catch((e) => setError(e.message));
  }, [subjectId]);
  async function adapt() {
    const book = books.find((b) => b.id === bookId);
    if (!book || !revisions.length) return;
    setLoading(true);
    setError("");
    try {
      const project = await miniApi.generateScript({
        subject_id: book.subject_id,
        book_revision_ids: revisions,
        idempotency_key: newRequestId(),
        duration_seconds: 60,
        audience: "family",
      });
      choose(project);
      setProjects((p) => [project, ...p.filter((s) => s.id !== project.id)]);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "改编未完成，请核对来源及任务状态",
      );
    } finally {
      setLoading(false);
    }
  }
  async function start() {
    if (!selected || !sceneId) return;
    setLoading(true);
    setError("");
    try {
      const run = await miniApi.startProduction({
        project_id: selected.id,
        scene_id: sceneId,
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
    <View className="page">
      <PreviewNotice />
      <Text className="title">影像 · 剧本与分镜</Text>
      {error && <Text className="error">{error}</Text>}
      <View className="card">
        <Text className="section-title">从已保存书稿改编</Text>
        <Text className="hint">
          先选择一本书，再选择已保存且来源有效的章节。改编剧本与生成视频分开计费。
        </Text>
        {books.map((book) => (
          <View key={book.id}>
            <Button
              className={
                bookId === book.id ? "primary-button" : "secondary-button"
              }
              onClick={() => {
                setBookId(book.id);
                setRevisions([]);
              }}
            >
              {book.title}
            </Button>
            {bookId === book.id &&
              book.chapters.map((ch) => (
                <Button
                  key={ch.id}
                  disabled={!ch.current || ch.stale || loading}
                  className={
                    ch.current && revisions.includes(ch.current.id)
                      ? "primary-button"
                      : "secondary-button"
                  }
                  onClick={() =>
                    ch.current &&
                    setRevisions((r) =>
                      r.includes(ch.current!.id)
                        ? r.filter((id) => id !== ch.current!.id)
                        : [...r, ch.current!.id],
                    )
                  }
                >
                  {ch.title}
                  {!ch.current
                    ? "（尚未成稿）"
                    : ch.stale
                      ? "（资料有更正）"
                      : ""}
                </Button>
              ))}
          </View>
        ))}
        <Button
          disabled={loading || !revisions.length}
          loading={loading}
          onClick={adapt}
        >
          改编为60秒剧本与分镜
        </Button>
        <Button
          onClick={() =>
            Taro.navigateTo({
              url: `/pages/books/index${subjectId ? `?subjectId=${subjectId}` : ""}`,
            })
          }
        >
          前往写书
        </Button>
      </View>
      <View className="card">
        <Text className="section-title">选择剧本与场景</Text>
        {projects.map((project) => (
          <Button
            key={project.id}
            onClick={() => choose(project)}
            className={
              selected?.id === project.id
                ? "primary-button"
                : "secondary-button"
            }
          >
            {project.title} · 第{project.version_number}版
          </Button>
        ))}
        {selected?.source_stale && (
          <Text className="error">
            书稿来源已有更正，请更新书稿并重新改编。
          </Text>
        )}
        {selected?.scenes.map((scene) => (
          <View
            key={scene.id}
            className="list-card"
            onClick={() => setSceneId(scene.id)}
          >
            <Text className="list-title">
              {sceneId === scene.id ? "✓ " : ""}
              {scene.heading} · {scene.duration_seconds}秒
            </Text>
            <Text className="list-meta">{scene.plot}</Text>
            {(scene.shots || []).map((shot, index) => (
              <Text className="hint" key={shot.id}>
                镜头{index + 1} · {shot.duration_seconds}秒 ·{" "}
                {shot.visual_prompt}
              </Text>
            ))}
          </View>
        ))}
        <Button
          disabled={
            loading ||
            !sceneId ||
            selected?.source_stale ||
            selected?.source_type !== "book"
          }
          loading={loading}
          onClick={start}
        >
          生成所选场景视频
        </Button>
      </View>
      <View className="section">
        <Text className="section-title">视频任务</Text>
        <Button
          onClick={() =>
            miniApi
              .productionRuns()
              .then(setRuns)
              .catch((e) => setError(e.message))
          }
        >
          刷新任务
        </Button>
        {runs.map((run) => (
          <View className="list-card" key={run.id}>
            <Text>
              {run.status} · {new Date(run.created_at).toLocaleString()}
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
                段
              </Text>
            )}
          </View>
        ))}
      </View>
    </View>
  );
}
