import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Person } from "@lifereel/contracts";
import { Pencil, Plus, UserRound } from "lucide-react";
import { type FormEvent, useState } from "react";
import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice, QueryState } from "../components/QueryState";
import { hasQueryIssue } from "../queryHelpers";
import { AccountDialog } from "../components/AccountDialog";

export function PeoplePage() {
  const queryClient = useQueryClient();
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [preferredName, setPreferredName] = useState("");
  const [birthYear, setBirthYear] = useState("");
  const [birthplace, setBirthplace] = useState("");
  const [isMinor, setIsMinor] = useState(false);
  const [guardianName, setGuardianName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);

  function resetForm() {
    setName("");
    setPreferredName("");
    setBirthYear("");
    setBirthplace("");
    setIsMinor(false);
    setGuardianName("");
    setEditingId(null);
  }

  function openCreate() {
    resetForm();
    setOpen(true);
  }

  function openEdit(person: Person) {
    setEditingId(person.id);
    setName(person.display_name);
    setPreferredName(person.preferred_name ?? "");
    setBirthYear(person.birth_year?.toString() ?? "");
    setBirthplace(person.birthplace ?? "");
    setIsMinor(person.is_minor);
    setGuardianName(person.guardian_name ?? "");
    setOpen(true);
  }

  const createPerson = useMutation({
    mutationFn: api.createPerson,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["persons"] });
      resetForm();
      setOpen(false);
    },
  });
  const updatePerson = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: Parameters<typeof api.updatePerson>[1];
    }) => api.updatePerson(id, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["persons"] });
      resetForm();
      setOpen(false);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const payload = {
      display_name: name,
      preferred_name: preferredName || null,
      birth_year: birthYear ? Number(birthYear) : null,
      birthplace: birthplace || null,
      is_subject: true,
      is_minor: isMinor,
      guardian_name: isMinor ? guardianName : null,
    };
    if (editingId) updatePerson.mutate({ id: editingId, payload });
    else createPerson.mutate(payload);
  }

  return (
    <div className="page">
      <div className="page-title-row">
        <div>
          <span className="eyebrow">人物与关系</span>
          <h1>我的家人</h1>
        </div>
        <Button
          variant="default"
          className="button primary"
          onClick={openCreate}
        >
          <Plus size={18} /> 添加家人
        </Button>
      </div>

      {hasQueryIssue([people]) ? (
        <QueryState queries={[people]} loadingText="正在读取人物档案……" />
      ) : people.data?.length ? (
        <div className="people-grid">
          {people.data.map((person) => (
            <article className="person-card" key={person.id}>
              <div className="avatar">{person.display_name.slice(0, 1)}</div>
              <div className="person-details">
                <h2>{person.preferred_name || person.display_name}</h2>
                <p>
                  {person.birth_year
                    ? `${person.birth_year} 年出生`
                    : "出生年份待补充"}
                </p>
                <small>{person.birthplace || "故乡待补充"}</small>
              </div>
              <Button
                variant="outline"
                size="icon"
                className="icon-button"
                title="编辑人物"
                aria-label={`编辑${person.display_name}`}
                onClick={() => openEdit(person)}
              >
                <Pencil size={17} />
              </Button>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={UserRound}
          title="先添加一位想被记录的人"
          description="可以是自己、父母、祖辈，或任何重要的人。"
        />
      )}

      {open && (
        <AccountDialog
          title={editingId ? "编辑人物档案" : "添加一位家人"}
          onClose={() => setOpen(false)}
          busy={createPerson.isPending || updatePerson.isPending}
        >
          <form className="account-form" onSubmit={submit}>
            <label>
              姓名
              <Input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如：林秀兰"
              />
            </label>
            <label>
              希望怎样称呼
              <Input
                value={preferredName}
                onChange={(e) => setPreferredName(e.target.value)}
                placeholder="例如：林奶奶"
              />
            </label>
            <div className="form-grid">
              <label>
                出生年份
                <Input
                  inputMode="numeric"
                  value={birthYear}
                  onChange={(e) => setBirthYear(e.target.value)}
                  placeholder="1952"
                />
              </label>
              <label>
                出生地
                <Input
                  value={birthplace}
                  onChange={(e) => setBirthplace(e.target.value)}
                  placeholder="福建泉州"
                />
              </label>
            </div>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={isMinor}
                onChange={(e) => setIsMinor(e.target.checked)}
              />{" "}
              未成年人档案
            </label>
            {isMinor && (
              <label>
                监护人姓名
                <Input
                  required
                  value={guardianName}
                  onChange={(e) => setGuardianName(e.target.value)}
                  placeholder="请输入监护人姓名"
                />
              </label>
            )}
            <ErrorNotice error={createPerson.error || updatePerson.error} />
            <div className="modal-actions">
              <Button
                variant="outline"
                type="button"
                className="button secondary"
                disabled={createPerson.isPending || updatePerson.isPending}
                onClick={() => {
                  setOpen(false);
                  resetForm();
                }}
              >
                取消
              </Button>
              <Button
                variant="default"
                className="button primary"
                disabled={createPerson.isPending || updatePerson.isPending}
              >
                保存人物
              </Button>
            </div>
          </form>
        </AccountDialog>
      )}
    </div>
  );
}
