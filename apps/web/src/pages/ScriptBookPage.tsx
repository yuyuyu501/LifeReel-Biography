import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ChevronRight,
  FileCheck2,
  Sparkles,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice, QueryState } from "../components/QueryState";
import { hasQueryIssue } from "../queryHelpers";

export function ScriptBookPage() {
  const { subjectId = "" } = useParams();
  const queryClient = useQueryClient();
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const chapters = useQuery({ queryKey: ["chapters"], queryFn: api.listChapters });
  const scripts = useQuery({ queryKey: ["scripts"], queryFn: api.listScripts });
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<"single_chapter" | "multi_chapter">("multi_chapter");
  const [chapterId, setChapterId] = useState("");
  const [selectedSceneId, setSelectedSceneId] = useState("");

  const person = people.data?.find((item) => item.id === subjectId);
  const personScripts = useMemo(
    () => scripts.data?.filter((project) => project.subject_id === subjectId) ?? [],
    [scripts.data, subjectId],
  );
  const project = personScripts[0];
  const selectedScene = project?.scenes.find((scene) => scene.id === selectedSceneId) ?? project?.scenes[0];

  useEffect(() => {
    if (!chapterId && chapters.data?.[0]) setChapterId(chapters.data[0].id);
  }, [chapterId, chapters.data]);

  useEffect(() => {
    if (!project?.scenes.length) {
      setSelectedSceneId("");
      return;
    }
    if (!project.scenes.some((scene) => scene.id === selectedSceneId)) {
      setSelectedSceneId(project.scenes[0].id);
    }
  }, [project, selectedSceneId]);

  const generate = useMutation({
    mutationFn: api.generateScript,
    onSuccess: async (updatedProject) => {
      setTitle("");
      setSelectedSceneId(updatedProject.scenes[0]?.id ?? "");
      await queryClient.invalidateQueries({ queryKey: ["scripts"] });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    generate.mutate({
      subject_id: subjectId,
      title: title || undefined,
      mode,
      audience: "family",
      chapter_id: mode === "single_chapter" ? chapterId : undefined,
    });
  }

  if (hasQueryIssue([people, chapters, scripts])) {
    return <div className="page"><QueryState queries={[people, chapters, scripts]} loadingText="正在打开人物书册……" /></div>;
  }
  if (!person) {
    return <div className="page"><EmptyState icon={FileCheck2} title="没有找到这本书" description="这位家人的档案可能已被移除。" /></div>;
  }

  const displayName = person.preferred_name || person.display_name;
  const currentChapter = chapters.data?.find((chapter) => chapter.id === selectedScene?.chapter_id);

  return (
    <div className="page script-book-page">
      <nav className="book-breadcrumb" aria-label="面包屑">
        <Link to="/scripts"><ArrowLeft size={16} /> 家庭书架</Link><ChevronRight size={14} /><span>{displayName}</span>
      </nav>

      <header className="book-detail-header">
        <div className="book-detail-cover" aria-hidden="true"><span>{displayName.slice(0, 1)}</span></div>
        <div>
          <span className="eyebrow">{person.relation_to_owner || "家庭成员"} · 人物书册</span>
          <h1>{displayName}的人生剧本</h1>
          <p>{person.birth_year ? `${person.birth_year} 年出生` : "出生年份待补充"}{person.birthplace ? `，来自${person.birthplace}` : ""}。目前收录 {project?.scenes.length ?? 0} 个剧本章节。</p>
        </div>
      </header>

      <section className="chapter-generator" aria-labelledby="generate-script-title">
        <div className="generator-heading">
          <div><span className="eyebrow">写入这本书</span><h2 id="generate-script-title">生成剧本章节</h2></div>
          <span className="generator-note"><Sparkles size={16} /> 采访内容会持续优化章节</span>
        </div>
        <form onSubmit={submit}>
          <label>剧本名称<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={project?.title || `${displayName}的生命片段`} /></label>
          <fieldset>
            <legend>生成结构</legend>
            <div className="mode-switch">
              <button type="button" className={mode === "single_chapter" ? "active" : ""} aria-pressed={mode === "single_chapter"} onClick={() => setMode("single_chapter")}>单章节</button>
              <button type="button" className={mode === "multi_chapter" ? "active" : ""} aria-pressed={mode === "multi_chapter"} onClick={() => setMode("multi_chapter")}>多章节</button>
            </div>
          </fieldset>
          {mode === "single_chapter" && <label>采访章节
            <select required value={chapterId} onChange={(event) => setChapterId(event.target.value)}>
              {chapters.data?.map((chapter) => <option key={chapter.id} value={chapter.id}>{String(chapter.order_index).padStart(2, "0")} · {chapter.title}</option>)}
            </select>
          </label>}
          <button className="button primary" disabled={generate.isPending || (mode === "single_chapter" && !chapterId)}>
            <Sparkles size={18} /> {generate.isPending ? "正在生成章节……" : mode === "multi_chapter" ? "生成整本剧本" : "生成所选章节"}
          </button>
        </form>
        <ErrorNotice error={generate.error} />
      </section>

      {project?.scenes.length ? (
        <section className="book-reading-layout" aria-label="剧本章节">
          <aside className="book-toc" aria-label="章节目录">
            <span className="eyebrow">书内目录</span>
            <div className="toc-heading-row">
              <h2>章节目录</h2>
              <span>{project.scenes.length} 章</span>
            </div>
            <div className="book-chapter-list">
              {project.scenes.map((scene) => (
                <div className={scene.id === selectedScene?.id ? "active" : ""} key={scene.id}>
                  <button onClick={() => setSelectedSceneId(scene.id)} aria-current={scene.id === selectedScene?.id ? "true" : undefined}>
                    <span>{String(scene.order_index).padStart(2, "0")}</span>
                    <span><strong>{scene.heading}</strong><small>{scene.duration_seconds} 秒 · {scene.source_claim_ids.length} 条记忆</small></span>
                  </button>
                </div>
              ))}
            </div>
          </aside>

          {selectedScene && <article className="book-manuscript">
            <header className="manuscript-header">
              <div>
                <span>{currentChapter ? `采访主题 · ${currentChapter.title}` : `第 ${String(selectedScene.order_index).padStart(2, "0")} 章`}</span>
                <h2>{project.title}</h2>
              </div>
            </header>
            <div className="manuscript-pages">
              <section className="manuscript-chapter">
                <div className="chapter-number">第 {String(selectedScene.order_index).padStart(2, "0")} 章</div>
                <h3>{selectedScene.heading}</h3>
                <p>{selectedScene.narration}</p>
                <div className="chapter-visual-note">
                  <strong>画面建议</strong>
                  <p>{selectedScene.visual_prompt}</p>
                </div>
                <footer><span>{selectedScene.duration_seconds} 秒</span><span>引用 {selectedScene.source_claim_ids.length} 条记忆</span></footer>
              </section>
            </div>
          </article>}
        </section>
      ) : (
        <EmptyState icon={FileCheck2} title="这本书还没有章节" description="使用上方生成工具，写下第一份剧本。" />
      )}
    </div>
  );
}
