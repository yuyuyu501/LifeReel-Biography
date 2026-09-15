import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

type Subject = { id: string; is_subject: boolean };
type Page = "interviews" | "memories" | "studio";

function readSelection(key: string) {
  try { return key ? localStorage.getItem(key) || "" : ""; } catch { return ""; }
}

// Only IDs are stored. Server-returned people remain the authority for access.
export function usePageSubject(page: Page, people: Subject[] | undefined, preferredId = "") {
  const client = useQueryClient();
  const user = client.getQueryData<{ id: string; tenant_id: string }>(["auth-me"]);
  const key = user?.id && user.tenant_id
    ? `lifereel:page-subject:${user.tenant_id}:${user.id}:${page}` : "";
  const [selection, setSelection] = useState<{ key: string; id: string } | null>(null);
  const requested = selection?.key === key ? selection.id : preferredId || readSelection(key);
  const subjects = people?.filter((person) => person.is_subject);
  const id = subjects?.find((person) => person.id === requested)?.id || subjects?.[0]?.id || "";

  useEffect(() => {
    if (!key || !people) return;
    try {
      if (id) localStorage.setItem(key, id);
      else localStorage.removeItem(key);
    } catch { /* Storage restrictions must not block the page. */ }
  }, [key, id, people]);

  return [id, (value: string) => setSelection({ key, id: value })] as const;
}
