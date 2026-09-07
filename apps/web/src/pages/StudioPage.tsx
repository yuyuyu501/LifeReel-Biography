import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, FileCheck2, Film, Play, RefreshCw, Send, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, generatedAssetUrl } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice, QueryState } from "../components/QueryState";
import { hasQueryIssue } from "../queryHelpers";
import { providerLabel, statusLabel } from "../statusLabels";

export function StudioPage() {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const [subjectId, setSubjectId] = useState("");
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const scripts = useQuery({ queryKey: ["scripts"], queryFn: api.listScripts });
  const productionRuns = useQuery({ queryKey: ["production-runs"], queryFn: api.listProductionRuns });
  const publications = useQuery({ queryKey: ["publications"], queryFn: api.listPublications });
  const consents = useQuery({ queryKey: ["consents"], queryFn: () => api.listConsents() });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });

  const requestedProject = scripts.data?.find((project) => project.id === searchParams.get("project"));
  const effectiveSubjectId = subjectId || requestedProject?.subject_id || people.data?.find((person) => person.is_subject)?.id || "";
  const subject = people.data?.find((person) => person.id === effectiveSubjectId);
  const subjectScripts = scripts.data?.filter((project) => project.subject_id === effectiveSubjectId) ?? [];
  const subjectProjectIds = new Set(subjectScripts.map((project) => project.id));
  const subjectRuns = productionRuns.data?.filter((run) => subjectProjectIds.has(run.project_id)) ?? [];
  const subjectJobs = jobs.data?.filter((job) => subjectProjectIds.has(String(job.payload.project_id ?? ""))) ?? [];
  const subjectConsents = consents.data?.filter((consent) => consent.subject_id === effectiveSubjectId) ?? [];
  const requiredConsentTypes = ["production", "portrait", "publication", ...(subject?.is_minor ? ["guardian"] : [])];
  const hasRequiredConsents = requiredConsentTypes.every((type) => subjectConsents.some((consent) => consent.consent_type === type && consent.scope === "family" && consent.status === "granted"));

  const grantConsents = useMutation({
    mutationFn: async () => {
      if (!subject) return;
      for (const consentType of requiredConsentTypes) {
        const alreadyGranted = subjectConsents.some((item) => item.consent_type === consentType && item.scope === "family" && item.status === "granted");
        if (!alreadyGranted) {
          await api.createConsent({
            subject_id: subject.id,
            consent_type: consentType as "production" | "portrait" | "publication" | "guardian",
            scope: "family",
            granted_by: subject.is_minor && consentType === "guardian" ? subject.guardian_name || "监护人" : "当前用户确认",
            evidence_note: "通过影像制作页记录；正式环境需关联电子签署证据。",
          });
        }
      }
    },
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["consents"] }),
  });
  const revokeConsent = useMutation({
    mutationFn: api.revokeConsent,
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["consents"] }),
  });
  const produce = useMutation({
    mutationFn: (projectId: string) => api.startProduction({ project_id: projectId, audience: "family" }),
    onSuccess: async () => Promise.all([
      queryClient.invalidateQueries({ queryKey: ["production-runs"] }),
      queryClient.invalidateQueries({ queryKey: ["jobs"] }),
    ]),
  });
  const publish = useMutation({
    mutationFn: (runId: string) => api.publish(runId, "family"),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["publications"] }),
  });
  const withdraw = useMutation({
    mutationFn: api.withdrawPublication,
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["publications"] }),
  });
  const retryJob = useMutation({
    mutationFn: api.retryJob,
    onSuccess: async () => Promise.all([
      queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      queryClient.invalidateQueries({ queryKey: ["production-runs"] }),
    ]),
  });

  const requiredQueries = [people, scripts, productionRuns, publications, consents, jobs];
  const actionError = grantConsents.error || revokeConsent.error || produce.error || publish.error || withdraw.error || retryJob.error;

  return (
    <div className="page film-studio-page">
      <header className="page-title-row">
        <div>
          <span className="eyebrow">从人物剧本到家庭成片</span>
          <h1>影像制作</h1>
          <p className="page-intro">这里只处理已经写好的剧本、制作授权、视频生成和家庭发布。新剧本请回到人物书册中创建。</p>
        </div>
        <Link className="button secondary" to={effectiveSubjectId ? `/scripts/${effectiveSubjectId}` : "/scripts"}>返回剧本书册</Link>
      </header>

      {hasQueryIssue(requiredQueries) ? <QueryState queries={requiredQueries} loadingText="正在准备影像制作台……" /> : <>
        <ErrorNotice error={actionError} />
        <div className="film-subject-bar">
          <label>制作对象
            <select value={effectiveSubjectId} onChange={(event) => setSubjectId(event.target.value)}>
              {people.data?.filter((person) => person.is_subject).map((person) => <option key={person.id} value={person.id}>{person.preferred_name || person.display_name}</option>)}
            </select>
          </label>
          <div className={hasRequiredConsents ? "film-readiness ready" : "film-readiness"}>
            <ShieldCheck size={20} />
            <div><strong>{hasRequiredConsents ? "制作授权已齐全" : "制作授权待补齐"}</strong><small>{subject?.preferred_name || subject?.display_name || "当前人物"} · 家人可见</small></div>
          </div>
          {!hasRequiredConsents && <button className="button primary" disabled={!subject || grantConsents.isPending} onClick={() => grantConsents.mutate()}><FileCheck2 size={17} /> 记录制作授权</button>}
        </div>

        <section className="section-block compact">
          <div className="section-heading"><div><span className="eyebrow">制作入口</span><h2>选择人物剧本</h2></div><p>剧本已有内容且人物授权齐全后，即可开始生成影像。</p></div>
          {subjectScripts.length ? <div className="film-script-list">{subjectScripts.map((project) => {
            const seconds = project.scenes.reduce((total, scene) => total + scene.duration_seconds, 0);
            const canProduce = project.scenes.length > 0 && hasRequiredConsents;
            return <article key={project.id} className={canProduce ? "ready" : ""}>
              <div className="film-script-icon"><Film size={20} /></div>
              <div><strong>{project.title}</strong><small>{project.scenes.length} 个章节 · 约 {seconds} 秒</small></div>
              {project.scenes.length ? <button className="button primary small" disabled={!hasRequiredConsents || produce.isPending} onClick={() => produce.mutate(project.id)}><Play size={15} /> 生成影像</button> : <Link className="button secondary small" to={`/scripts/${project.subject_id}`}>继续整理剧本</Link>}
            </article>;
          })}</div> : <EmptyState icon={Film} title="还没有可制作的剧本" description="先进入这位家人的书册，生成剧本章节。" />}
        </section>

        {subjectRuns.length ? <section className="section-block compact">
          <div className="section-heading"><div><span className="eyebrow">生产与发布</span><h2>成片任务</h2></div></div>
          <div className="production-grid">{subjectRuns.map((run) => {
            const publication = publications.data?.find((item) => item.production_run_id === run.id && item.status === "published");
            return <article className="production-card" key={run.id}>
              <div><span className={`run-status ${run.status}`}>{statusLabel(run.status)}</span><h3>{scripts.data?.find((item) => item.id === run.project_id)?.title || "影传成片"}</h3><p>生成服务：{providerLabel(run.provider)} · 范围：{statusLabel(run.audience)}</p></div>
              {run.assets[0]?.mime_type === "video/mp4" && <video controls preload="metadata" src={generatedAssetUrl(run.assets[0].id)} />}
              {publication ? <div className="publication-actions"><div className="notice success">家庭访问令牌：{publication.access_token.slice(0, 10)}…</div><button className="button secondary small danger" disabled={withdraw.isPending} onClick={() => withdraw.mutate(publication.id)}><Ban size={15} /> 撤回发布</button></div> : <button className="button primary small" disabled={publish.isPending || run.status !== "completed"} onClick={() => publish.mutate(run.id)}><Send size={16} /> 发布给家人</button>}
            </article>;
          })}</div>
        </section> : null}

        {subjectConsents.length ? <section className="section-block compact">
          <div className="section-heading"><div><span className="eyebrow">隐私与使用边界</span><h2>本人物授权</h2></div></div>
          <div className="management-list">{subjectConsents.map((consent) => <article key={consent.id}><div><strong>{statusLabel(consent.consent_type, "其他授权")}</strong><small>{statusLabel(consent.scope)} · {statusLabel(consent.status)}</small></div>{consent.status === "granted" && <button className="button secondary small danger" disabled={revokeConsent.isPending} onClick={() => revokeConsent.mutate(consent.id)}><Ban size={15} /> 撤销授权</button>}</article>)}</div>
        </section> : null}

        {subjectJobs.length ? <section className="section-block compact">
          <div className="section-heading"><div><span className="eyebrow">后台处理</span><h2>任务记录</h2></div></div>
          <div className="management-list">{subjectJobs.map((job) => <article key={job.id}><div><strong>{statusLabel(job.kind, "后台任务")}</strong><small>{statusLabel(job.status)} · 已尝试 {job.attempt_count} 次{job.error_code ? ` · ${statusLabel(job.error_code, "处理失败")}` : ""}</small></div>{["failed", "cancelled"].includes(job.status) && <button className="button secondary small" disabled={retryJob.isPending} onClick={() => retryJob.mutate(job.id)}><RefreshCw size={15} /> 重试</button>}</article>)}</div>
        </section> : null}
      </>}
    </div>
  );
}
