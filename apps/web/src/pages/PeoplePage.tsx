import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Person } from "@lifereel/contracts";
import { Pencil, Plus, Trash2, UserRound } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice, QueryState } from "../components/QueryState";
import { hasQueryIssue } from "../queryHelpers";
import { AccountDialog } from "../components/AccountDialog";

export function PeoplePage() {
  const queryClient = useQueryClient();
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState(params.get("create") === "1");
  const [name, setName] = useState("");
  const [preferredName, setPreferredName] = useState("");
  const [birthYear, setBirthYear] = useState("");
  const [birthplace, setBirthplace] = useState("");
  const [isMinor, setIsMinor] = useState(false);
  const [guardianName, setGuardianName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [notice, setNotice] = useState("");

  function resetForm() {
    if (params.has("create")) {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          next.delete("create");
          return next;
        },
        { replace: true },
      );
    }
    setName("");
    setPreferredName("");
    setBirthYear("");
    setBirthplace("");
    setIsMinor(false);
    setGuardianName("");
    setEditingId(null);
    setEditingName("");
    setConfirmDelete(false);
    deletePerson.reset();
    createPerson.reset();
    updatePerson.reset();
  }

  function openCreate() {
    resetForm();
    setNotice("");
    setOpen(true);
  }

  function openEdit(person: Person) {
    resetForm();
    setNotice("");
    setEditingId(person.id);
    setEditingName(person.display_name);
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
  const deletePerson = useMutation({
    mutationFn: (personId: string) => api.deletePerson(personId),
    onSuccess: async () => {
      // Other pages can retain selected subjects and cached books/interviews.
      // Refetch active queries and mark all remaining data stale.
      await queryClient.invalidateQueries();
      setNotice(`已删除家人「${editingName}」及其关联记录。`);
      setOpen(false);
      resetForm();
    },
  });
  const busy =
    createPerson.isPending || updatePerson.isPending || deletePerson.isPending;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || confirmDelete) return;
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

      {notice && <p role="status">{notice}</p>}
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
          title={
            confirmDelete
              ? "确认删除家人"
              : editingId
                ? "编辑人物档案"
                : "添加一位家人"
          }
          onClose={() => setOpen(false)}
          busy={busy}
        >
          {confirmDelete ? (
            <div className="account-form">
              <p>
                确定删除家人「{editingName}」吗？该家人的人物档案、采访记录、
                记忆资料、书稿、剧本及影像记录将从账号中删除，无法在页面恢复。
              </p>
              <p>
                其他家人的资料和账号余额不受影响，历史消费记录保留。已上传的原始文件和
                生成文件会保留在存储中，需另行联系管理员处理。
              </p>
              <ErrorNotice error={deletePerson.error} />
              <div className="modal-actions person-delete-confirm-actions">
                <Button
                  variant="outline"
                  type="button"
                  disabled={busy}
                  autoFocus
                  onClick={() => {
                    setConfirmDelete(false);
                    deletePerson.reset();
                  }}
                >
                  返回编辑
                </Button>
                <Button
                  variant="destructive"
                  type="button"
                  disabled={busy}
                  onClick={() => editingId && deletePerson.mutate(editingId)}
                >
                  {deletePerson.isPending ? "正在删除…" : "确认删除家人"}
                </Button>
              </div>
            </div>
          ) : (
            <form className="account-form" onSubmit={submit}>
              <fieldset disabled={busy} className="person-edit-fields">
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
              </fieldset>
              <ErrorNotice error={createPerson.error || updatePerson.error} />
              {editingId && (
                <div className="person-delete-action">
                  <Button
                    variant="destructive"
                    type="button"
                    disabled={busy}
                    onClick={() => setConfirmDelete(true)}
                  >
                    <Trash2 size={16} /> 删除家人
                  </Button>
                  <small>删除前会再次确认，并说明关联内容的处理。</small>
                </div>
              )}
              <div className="modal-actions">
                <Button
                  variant="outline"
                  type="button"
                  className="button secondary"
                  disabled={busy}
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
                  disabled={busy}
                >
                  保存人物
                </Button>
              </div>
            </form>
          )}
        </AccountDialog>
      )}
    </div>
  );
}
