import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpenText,
  Circle,
  Mic2,
  UserRound,
  UserRoundPlus,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { Button } from "../components/ui/button";
import { QueryState } from "../components/QueryState";
import { hasQueryIssue } from "../queryHelpers";
import { usePageSubject } from "../usePageSubject";
import { InterviewWorkspace } from "./InterviewRoomPage";

export function InterviewsPage() {
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const [params, setParams] = useSearchParams();
  const [subjectId, setSubjectId] = usePageSubject(
    "interviews",
    people.data,
    params.get("subject") || "",
  );
  const subject = people.data?.find((p) => p.id === subjectId);
  const session = useQuery({
    queryKey: ["life-interview", subjectId],
    // This endpoint returns the same person-level session on repeated calls.
    queryFn: () => api.startInterview({ subject_id: subjectId }),
    enabled: !!subject,
    staleTime: Infinity,
    retry: false,
  });
  if (hasQueryIssue([people]))
    return (
      <div className="page">
        <QueryState queries={[people]} />
      </div>
    );
  if (!subject)
    return (
      <div className="page interview-empty-page">
        <header className="interview-empty-heading">
          <div>
            <h1>
              <UserRound size={28} aria-hidden="true" />
              人物采访
            </h1>
            <p>记录家人的经历与记忆。</p>
          </div>
          <Link to="/people?create=1" className="interview-first-step">
            <Circle size={14} aria-hidden="true" />第 1 步：添加人物
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </header>
        <section
          className="interview-empty-start"
          aria-labelledby="interview-empty-title"
        >
          <img
            src="/images/interview-empty.webp"
            alt=""
            width="360"
            height="310"
          />
          <div className="interview-empty-copy">
            <h2 id="interview-empty-title">添加人物后，开始第一次采访</h2>
            <p>
              先建立要记录的人物档案，再为 TA 留下人生故事。
              <br />
              每位家人的资料独立保存。
            </p>
            <Button asChild className="interview-empty-add">
              <Link to="/people?create=1">
                <UserRoundPlus size={20} />
                添加人物
              </Link>
            </Button>
          </div>
        </section>
        <ol className="interview-empty-process" aria-label="记录流程">
          {[
            { icon: UserRound, title: "添加人物", detail: "独立的人生档案" },
            { icon: Mic2, title: "发起采访", detail: "回忆具体的人与事" },
            {
              icon: BookOpenText,
              title: "整理故事",
              detail: "留下可回看的记忆",
            },
          ].map(({ icon: Icon, title, detail }, index) => (
            <li key={title}>
              <span className="interview-step-number">{index + 1}</span>
              <Icon size={27} aria-hidden="true" />
              <div>
                <strong>{title}</strong>
                <p>{detail}</p>
              </div>
              {index < 2 && (
                <ArrowRight
                  className="interview-step-arrow"
                  size={18}
                  aria-hidden="true"
                />
              )}
            </li>
          ))}
        </ol>
      </div>
    );
  if (hasQueryIssue([session]))
    return (
      <div className="page">
        <QueryState queries={[session]} loadingText="正在打开采访工作台……" />
      </div>
    );
  return (
    <InterviewWorkspace
      key={session.data!.id}
      id={session.data!.id}
      subjectPicker={{
        people: people.data!,
        onChange: (id) => {
          setSubjectId(id);
          setParams(
            (previous) => {
              const next = new URLSearchParams(previous);
              next.set("subject", id);
              return next;
            },
            { replace: true },
          );
        },
      }}
    />
  );
}
