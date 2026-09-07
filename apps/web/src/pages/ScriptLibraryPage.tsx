import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpenText, LibraryBig } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { QueryState } from "../components/QueryState";
import { hasQueryIssue } from "../queryHelpers";

function personName(person: { display_name: string; preferred_name: string | null }) {
  return person.preferred_name || person.display_name;
}

export function ScriptLibraryPage() {
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const scripts = useQuery({ queryKey: ["scripts"], queryFn: api.listScripts });
  const subjects = people.data?.filter((person) => person.is_subject) ?? [];

  return (
    <div className="page script-library-page">
      <header className="page-title-row library-title-row">
        <div>
          <span className="eyebrow">家庭剧本书库</span>
          <h1>一位家人，一本人生之书</h1>
          <p className="page-intro">每本书只收录一位家人的剧本。打开书册，查看章节或根据新的采访内容继续整理。</p>
        </div>
        <div className="library-mark" aria-hidden="true"><LibraryBig size={25} /></div>
      </header>

      {hasQueryIssue([people, scripts]) ? (
        <QueryState queries={[people, scripts]} loadingText="正在整理家庭书架……" />
      ) : subjects.length ? (
        <section className="family-bookshelf" aria-label="家庭成员剧本书架">
          {subjects.map((person, index) => {
            const project = scripts.data?.find((item) => item.subject_id === person.id);
            const chapterCount = project?.scenes.length ?? 0;
            return (
              <Link className={`family-book book-tone-${index % 3}`} to={`/scripts/${person.id}`} key={person.id}>
                <span className="book-spine" aria-hidden="true" />
                <span className="book-cover-index">家庭口述史 · 第 {String(index + 1).padStart(2, "0")} 册</span>
                <span className="book-cover-monogram" aria-hidden="true">{personName(person).slice(0, 1)}</span>
                <span className="book-cover-copy">
                  <strong>{personName(person)}</strong>
                  <small>{person.birth_year ? `${person.birth_year} 年出生` : "出生年份待补充"}{person.birthplace ? ` · ${person.birthplace}` : ""}</small>
                </span>
                <span className="book-cover-meta">
                  <span>{project ? "已有剧本" : "尚未生成"}</span>
                  <span>{chapterCount} 个章节</span>
                </span>
                <span className="book-open-action">{project ? "继续编写" : "开始第一章"}<ArrowRight size={17} /></span>
              </Link>
            );
          })}
          <div className="bookshelf-line" aria-hidden="true" />
        </section>
      ) : (
        <EmptyState icon={BookOpenText} title="书架上还没有家人的书" description="先建立一位家人的人物档案，再回来开始整理章节。" />
      )}
    </div>
  );
}
