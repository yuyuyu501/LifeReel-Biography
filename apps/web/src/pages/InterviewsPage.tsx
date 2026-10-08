import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mic2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { profilesApi } from "../api/profiles";
import { EmptyState } from "../components/EmptyState";
import { LifeProfileTable } from "../components/LifeProfileTable";
import { ErrorNotice, QueryState } from "../components/QueryState";
import { Button } from "../components/ui/button";
import { hasQueryIssue } from "../queryHelpers";
import { usePageSubject } from "../usePageSubject";

export function InterviewsPage() {
  const cache = useQueryClient();
  const navigate = useNavigate();
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const interviews = useQuery({
    queryKey: ["interviews"],
    queryFn: api.listInterviews,
  });
  const [subjectId, setSubjectId] = usePageSubject("interviews", people.data);
  const subject = people.data?.find((p) => p.id === subjectId);
  const profile = useQuery({
    queryKey: ["life-profile", subjectId],
    queryFn: () => profilesApi.subject(subjectId),
    enabled: !!subject,
  });
  const start = useMutation({
    mutationFn: api.startInterview,
    onSuccess: async (session) => {
      await cache.invalidateQueries({ queryKey: ["interviews"] });
      navigate(`/interviews/${session.id}`);
    },
  });
  if (hasQueryIssue([people, interviews]))
    return (
      <div className="page">
        <QueryState queries={[people, interviews]} />
      </div>
    );
  return (
    <div className="page life-interviews-page">
      <header className="page-title-row">
        <div>
          <span className="eyebrow">一份资料，多次讲述</span>
          <h1>人生采访</h1>
          <p>AI 会帮助整理资料、补问空缺。可以自由讲述，也可以直接填写表格。</p>
        </div>
      </header>
      {!subject ? (
        <EmptyState
          icon={Mic2}
          title="添加人物后再开始采访"
          description="先选择要记录的人物，建立独立的人生资料。"
        />
      ) : (
        <>
          <div className="toolbar-row">
            <label>
              采访人物
              <select
                value={subjectId}
                onChange={(e) => setSubjectId(e.target.value)}
              >
                {people.data
                  ?.filter((p) => p.is_subject)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.preferred_name || p.display_name}
                    </option>
                  ))}
              </select>
            </label>
            <Button
              disabled={start.isPending}
              onClick={() => start.mutate({ subject_id: subject.id })}
            >
              {start.isPending ? "正在进入……" : "开始或继续采访"}
            </Button>
          </div>
          <ErrorNotice error={start.error} />
          <QueryState queries={[profile]} loadingText="正在读取人生资料……" />
          {profile.data && (
            <LifeProfileTable key={profile.data.id} profile={profile.data} />
          )}
          <details className="profile-legacy">
            <summary>查看以前的采访记录</summary>
            {interviews.data
              ?.filter((s) => s.subject_id === subjectId && !s.profile_id)
              .map((s) => (
                <p key={s.id}>
                  <Link to={`/interviews/${s.id}`}>
                    {new Date(s.started_at).toLocaleDateString()} · 历史对话
                  </Link>
                </p>
              ))}
          </details>
        </>
      )}
    </div>
  );
}
