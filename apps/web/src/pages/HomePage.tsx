import { Button } from "../components/ui/button";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpenText,
  CheckCircle2,
  CircleDashed,
  Film,
  FolderArchive,
  Mic2,
  UsersRound,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { QueryState } from "../components/QueryState";
import { hasQueryIssue } from "../queryHelpers";

export function HomePage() {
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const interviews = useQuery({
    queryKey: ["interviews"],
    queryFn: api.listInterviews,
  });
  const evidence = useQuery({
    queryKey: ["evidence"],
    queryFn: () => api.listEvidence(),
  });
  const scripts = useQuery({ queryKey: ["scripts"], queryFn: api.listScripts });
  const overviewQueries = [people, interviews, evidence, scripts];
  const activeInterview = interviews.data?.[0];
  const latestInterview = interviews.data?.[0];
  const nextAction = activeInterview
    ? {
        to: `/interviews/${activeInterview.id}`,
        label: "继续上次采访",
        description: `已记录 ${activeInterview.round_count} 轮对话，原有内容均已保存。`,
        icon: Mic2,
      }
    : people.data?.length
      ? {
          to: "/interviews",
          label: "开始一段采访",
          description: "选择人生章节，从一个具体问题自然聊起。",
          icon: Mic2,
        }
      : {
          to: "/people",
          label: "建立第一份人物档案",
          description: "先记录姓名、称呼和基础生平，再开始采访。",
          icon: UsersRound,
        };
  const NextIcon = nextAction.icon;

  return (
    <div className="page home-page">
      <header className="page-title-row home-title-row">
        <div>
          <span className="eyebrow">档案工作台 · 今日概览</span>
          <h1>继续整理这份人生</h1>
          <p className="page-intro">
            从原声采访到家庭影传，每一条记忆都有来源，每一步发布都需要确认。
          </p>
        </div>
        <Button asChild variant="default" className="button primary">
          <Link to={nextAction.to}>
            <NextIcon size={18} />
            {nextAction.label}
            <ArrowRight size={17} />
          </Link>
        </Button>
      </header>

      {hasQueryIssue(overviewQueries) ? (
        <QueryState
          queries={overviewQueries}
          loadingText="正在读取档案概览……"
        />
      ) : (
        <>
          <section className="home-dashboard" aria-label="今日工作概览">
            <article className="next-task-panel">
              <div className="task-kicker">
                <span className="live-mark" /> 建议下一步
              </div>
              <div className="task-icon">
                <NextIcon size={28} />
              </div>
              <h2>{nextAction.label}</h2>
              <p>{nextAction.description}</p>
              <Button
                asChild
                variant="link"
                className="text-button px-0 justify-start"
              >
                <Link to={nextAction.to}>
                  进入处理 <ArrowRight size={17} />
                </Link>
              </Button>
            </article>
            <div className="archive-summary">
              <div className="archive-summary-head">
                <div>
                  <span className="eyebrow">档案索引</span>
                  <h2>当前收录</h2>
                </div>
                <FolderArchive size={24} />
              </div>
              <dl className="metric-list">
                <div>
                  <dt>人物档案</dt>
                  <dd>
                    {people.data?.length ?? 0}
                    <small>人</small>
                  </dd>
                </div>
                <div>
                  <dt>采访记录</dt>
                  <dd>
                    {interviews.data?.length ?? 0}
                    <small>次</small>
                  </dd>
                </div>
                <div>
                  <dt>回忆文件</dt>
                  <dd>
                    {evidence.data?.length ?? 0}
                    <small>份</small>
                  </dd>
                </div>
                <div>
                  <dt>剧本草稿</dt>
                  <dd>
                    {scripts.data?.length ?? 0}
                    <small>部</small>
                  </dd>
                </div>
              </dl>
            </div>
          </section>

          <section className="section-block workflow-section">
            <div className="section-heading">
              <div>
                <span className="eyebrow">制作轨道</span>
                <h2>从讲述到成片</h2>
              </div>
              <p>采访持续整理剧本，影像制作和发布仍需人物授权。</p>
            </div>
            <div className="workflow-track">
              <Link
                to="/people"
                className={people.data?.length ? "done" : "current"}
              >
                <span>
                  {people.data?.length ? <CheckCircle2 /> : <CircleDashed />}
                </span>
                <strong>人物</strong>
                <small>{people.data?.length ? "已建立档案" : "等待建立"}</small>
              </Link>
              <Link
                to="/interviews"
                className={
                  interviews.data?.length
                    ? "done"
                    : people.data?.length
                      ? "current"
                      : ""
                }
              >
                <span>
                  {interviews.data?.length ? <CheckCircle2 /> : <Mic2 />}
                </span>
                <strong>采访</strong>
                <small>
                  {interviews.data?.length
                    ? `${interviews.data.length} 次记录`
                    : "尚未开始"}
                </small>
              </Link>
              <Link
                to="/memories"
                className={evidence.data?.length ? "done" : ""}
              >
                <span>
                  {evidence.data?.length ? <CheckCircle2 /> : <BookOpenText />}
                </span>
                <strong>记忆</strong>
                <small>
                  {evidence.data?.length
                    ? `${evidence.data.length} 份文件 · 记忆图谱`
                    : "等待采访沉淀"}
                </small>
              </Link>
              <Link
                to="/scripts"
                className={scripts.data?.length ? "done" : ""}
              >
                <span>
                  <BookOpenText />
                </span>
                <strong>剧本</strong>
                <small>
                  {scripts.data?.length
                    ? `${scripts.data.length} 份草稿`
                    : "等待创作"}
                </small>
              </Link>
              <Link to="/studio">
                <span>
                  <Film />
                </span>
                <strong>影像</strong>
                <small>授权后进入制作</small>
              </Link>
            </div>
          </section>

          <section className="home-lower-grid is-single">
            <div className="activity-panel">
              <div className="section-heading compact-heading">
                <div>
                  <span className="eyebrow">最近记录</span>
                  <h2>工作动态</h2>
                </div>
              </div>
              {latestInterview ? (
                <Link
                  className="activity-row"
                  to={`/interviews/${latestInterview.id}`}
                >
                  <span className="activity-icon">
                    <Mic2 size={18} />
                  </span>
                  <div>
                    <strong>采访已保存</strong>
                    <small>
                      {latestInterview.round_count} 轮对话 ·{" "}
                      {latestInterview.status === "completed"
                        ? "已完成"
                        : "可继续"}
                    </small>
                  </div>
                  <ArrowRight size={17} />
                </Link>
              ) : (
                <div className="activity-empty">
                  完成第一段采访后，最近记录会显示在这里。
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
