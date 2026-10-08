import { useQuery } from "@tanstack/react-query";
import { Mic2 } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
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
      <div className="page">
        <EmptyState
          icon={Mic2}
          title="添加人物后再开始采访"
          description="先选择要记录的人物，建立独立的人生资料。"
        />
        <Link to="/people" className="profile-next">
          添加人物
        </Link>
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
