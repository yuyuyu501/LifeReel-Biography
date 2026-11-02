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
import { booksApi } from "../api/books";
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
  const books = useQuery({ queryKey: ["books"], queryFn: booksApi.list });
  const overviewQueries = [people, interviews, evidence, scripts, books];
  const recordedInterviews =
    interviews.data?.filter((session) =>
      session.rounds.some((round) => round.answer_text?.trim()),
    ) ?? [];
  const activeInterview = [...recordedInterviews]
    .filter((session) => session.profile_id && session.status !== "completed")
    .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))[0];
  const draftedBooks =
    books.data?.filter((book) =>
      book.chapters.some((chapter) => chapter.current),
    ) ?? [];
  const nextAction = activeInterview
    ? {
        to: `/interviews/${activeInterview.id}`,
        label: "继续上次采访",
        description: `已记录 ${activeInterview.rounds.filter((round) => round.answer_text?.trim()).length} 轮回答，原有内容均已保存。`,
        icon: Mic2,
      }
    : people.data?.length
      ? {
          to: "/interviews",
          label: "开始一段采访",
          description: "选择人物，从一段想讲的经历开始，逐步补齐人生资料。",
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
        <div className="home-hero-copy">
          <span className="eyebrow">档案工作台 · 今日概览</span>
          <h1>继续整理这份人生</h1>
          <p className="page-intro">
            从原声采访到家庭影传，每一条记忆都有来源，内容仅在当前账号内可见。
          </p>
        </div>
        <div className="home-hero-action">
          <span>建议下一步</span>
          <Button asChild variant="default" className="button primary">
            <Link to={nextAction.to}>
              <NextIcon size={18} />
              {nextAction.label}
              <ArrowRight size={17} />
            </Link>
          </Button>
        </div>
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
                    {recordedInterviews.length}
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
              <p>
                采访整理人生资料，写书保存正文，影像再从书稿改编剧本与分镜。
              </p>
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
                  recordedInterviews.length
                    ? "done"
                    : people.data?.length
                      ? "current"
                      : ""
                }
              >
                <span>
                  {recordedInterviews.length ? <CheckCircle2 /> : <Mic2 />}
                </span>
                <strong>采访</strong>
                <small>
                  {recordedInterviews.length
                    ? `${recordedInterviews.length} 份对话记录`
                    : "尚未开始"}
                </small>
              </Link>
              <Link to="/memories" className="">
                <span>
                  <BookOpenText />
                </span>
                <strong>记忆</strong>
                <small>
                  {evidence.data?.length
                    ? `${evidence.data.length} 份素材 · 可查看整理结果`
                    : "等待采访沉淀"}
                </small>
              </Link>
              <Link
                to="/books"
                className={draftedBooks.length ? "current" : ""}
              >
                <span>
                  <BookOpenText />
                </span>
                <strong>写书</strong>
                <small>
                  {books.data?.length
                    ? `${draftedBooks.length} 本已有成稿 · ${books.data.length} 本书籍`
                    : "等待创作"}
                </small>
              </Link>
              <Link to="/studio">
                <span>
                  <Film />
                </span>
                <strong>影像</strong>
                <small>书稿改编 · 账号私密</small>
              </Link>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
