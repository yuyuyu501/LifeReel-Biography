import { Button } from "../components/ui/button";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Clock3, MessageCircle, Mic2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice, QueryState } from "../components/QueryState";
import { hasQueryIssue } from "../queryHelpers";
import { usePageSubject } from "../usePageSubject";

export function InterviewsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const chapters = useQuery({
    queryKey: ["chapters"],
    queryFn: api.listChapters,
  });
  const interviews = useQuery({
    queryKey: ["interviews"],
    queryFn: api.listInterviews,
  });
  const [subjectId, setSubjectId] = usePageSubject("interviews", people.data);

  const start = useMutation({
    mutationFn: api.startInterview,
    onSuccess: async (session) => {
      await queryClient.invalidateQueries({ queryKey: ["interviews"] });
      navigate(`/interviews/${session.id}`);
    },
  });

  const subject = people.data?.find((person) => person.id === subjectId);
  const requiredQueries = [people, chapters, interviews];
  const subjectSessions =
    interviews.data
      ?.filter((session) => session.subject_id === subject?.id)
      .sort(
        (left, right) =>
          new Date(right.started_at).getTime() -
          new Date(left.started_at).getTime(),
      ) ?? [];
  const chapterSessions = new Map<string, (typeof subjectSessions)[number]>();
  subjectSessions.forEach((session) => {
    if (session.chapter_id && !chapterSessions.has(session.chapter_id)) {
      chapterSessions.set(session.chapter_id, session);
    }
  });
  const pastSessions = subjectSessions.filter(
    (session) =>
      !session.chapter_id ||
      chapterSessions.get(session.chapter_id)?.id !== session.id,
  );

  return (
    <div className="page">
      <div className="page-title-row">
        <div>
          <span className="eyebrow">一章一段长期对话</span>
          <h1>章节采访</h1>
        </div>
      </div>

      {hasQueryIssue(requiredQueries) ? (
        <QueryState
          queries={requiredQueries}
          loadingText="正在准备采访空间……"
        />
      ) : !subject ? (
        <EmptyState
          icon={Mic2}
          title="添加人物后再开始采访"
          description="先告诉我们要记录谁，系统才能建立独立的生命记忆。"
        />
      ) : (
        <>
          <div className="toolbar-row">
            <label>
              采访人物
              <select
                value={subject.id}
                onChange={(event) => setSubjectId(event.target.value)}
              >
                {people.data
                  ?.filter((person) => person.is_subject)
                  .map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.preferred_name || person.display_name}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          <ErrorNotice error={start.error} />
          <section className="chapter-grid" aria-label="采访章节">
            {chapters.data?.map((chapter) => {
              const existing = chapterSessions.get(chapter.id);
              const answerCount =
                existing?.rounds.filter((round) => round.answer_text).length ??
                0;
              const isStarting =
                start.isPending && start.variables?.chapter_id === chapter.id;
              return (
                <article
                  className={`chapter-card interview-chapter-card ${existing ? "has-session" : ""}`}
                  key={chapter.id}
                >
                  <div className="chapter-card-kicker">
                    <span>
                      第 {String(chapter.order_index).padStart(2, "0")} 章
                    </span>
                  </div>
                  <h2>{chapter.title}</h2>
                  <p>{chapter.description}</p>
                  <div className="chapter-saved-progress">
                    <MessageCircle size={15} aria-hidden="true" />
                    {existing
                      ? `已保存 ${answerCount} 轮回答`
                      : "等待第一段讲述"}
                  </div>
                  <Button
                    variant="link"
                    className="text-button"
                    disabled={start.isPending}
                    onClick={() =>
                      existing
                        ? navigate(`/interviews/${existing.id}`)
                        : start.mutate({
                            subject_id: subject.id,
                            chapter_id: chapter.id,
                          })
                    }
                  >
                    {isStarting
                      ? "正在建立记录"
                      : !existing
                        ? "开始这一章"
                        : "继续这一章"}{" "}
                    <ArrowRight size={17} />
                  </Button>
                </article>
              );
            })}
          </section>

          {pastSessions.length > 0 && (
            <section className="section-block compact">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">历史存档</span>
                  <h2>过往采访</h2>
                </div>
              </div>
              <div className="session-list">
                {pastSessions.map((session) => (
                  <Link
                    className="session-row"
                    to={`/interviews/${session.id}`}
                    key={session.id}
                  >
                    <span className="session-status">
                      <Mic2 size={18} />
                    </span>
                    <div>
                      <strong>
                        {chapters.data?.find(
                          (item) => item.id === session.chapter_id,
                        )?.title ?? "自由采访"}
                      </strong>
                      <small>
                        <Clock3 size={14} /> 已保存{" "}
                        {
                          session.rounds.filter((round) => round.answer_text)
                            .length
                        }{" "}
                        轮回答
                      </small>
                    </div>
                    <ArrowRight size={18} />
                  </Link>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
