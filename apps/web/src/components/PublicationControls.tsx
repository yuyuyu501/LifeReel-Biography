import type { Person, Publication } from "@lifereel/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { AccountDialog } from "./AccountDialog";
import { ErrorNotice, QueryState } from "./QueryState";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

export function PublicationControls({
  runId,
  person,
  publication,
}: {
  runId: string;
  person: Person;
  publication?: Publication;
}) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [grantor, setGrantor] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [revokeId, setRevokeId] = useState("");
  const consents = useQuery({
    queryKey: ["consents", person.id],
    queryFn: () => api.listConsents(person.id),
    enabled: open,
    staleTime: 0,
  });
  const grants = (consents.data ?? []).filter(
    (grant) =>
      grant.consent_type === "publication" &&
      grant.status === "granted" &&
      (!grant.expires_at || Date.parse(grant.expires_at) > Date.now()) &&
      ["family", "friends", "public"].includes(grant.scope),
  );
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["consents", person.id] }),
      client.invalidateQueries({ queryKey: ["publications"] }),
    ]);
  };
  const publish = useMutation({
    mutationFn: async () => {
      if (!confirmed || (!grants.length && !grantor.trim()))
        throw new Error("请填写授权人并确认发布范围。");
      if (!grants.length) {
        await api.createConsent({
          subject_id: person.id,
          consent_type: "publication",
          scope: "family",
          granted_by: grantor.trim(),
          evidence_note: "用户在发布窗口确认已获得本人或监护人的分享授权",
        });
        // Preserve the successful grant when publishing fails, so retrying does
        // not create another authorization.
        await client.invalidateQueries({ queryKey: ["consents", person.id] });
      }
      return api.publish(runId, "family");
    },
    onSuccess: async () => {
      await refresh();
      setOpen(false);
      setConfirmed(false);
    },
  });
  const withdraw = useMutation({
    mutationFn: api.withdrawPublication,
    onSuccess: refresh,
  });
  const revoke = useMutation({
    mutationFn: api.revokeConsent,
    onSuccess: async () => {
      setRevokeId("");
      setConfirmed(false);
      await refresh();
    },
  });
  const busy = publish.isPending || withdraw.isPending || revoke.isPending;
  const shareUrl = publication
    ? `${window.location.origin}/watch/${publication.access_token}`
    : "";

  return (
    <div className="studio-publish-row flex-wrap">
      {publication ? (
        <>
          <label className="min-w-0 flex-1">
            家人分享链接
            <Input
              aria-label="家人分享链接"
              value={shareUrl}
              readOnly
              onFocus={(event) => event.target.select()}
            />
          </label>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={() => withdraw.mutate(publication.id)}
          >
            {withdraw.isPending ? "正在撤回" : "撤回发布"}
          </Button>
        </>
      ) : (
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => {
            publish.reset();
            revoke.reset();
            setConfirmed(false);
            setOpen(true);
          }}
        >
          发布给家人
        </Button>
      )}
      <Button
        variant="outline"
        disabled={busy}
        onClick={() => {
          publish.reset();
          revoke.reset();
          setConfirmed(false);
          setOpen(true);
        }}
      >
        管理发布授权
      </Button>
      <ErrorNotice error={withdraw.error} />
      {open && (
        <AccountDialog
          title={`${person.display_name}的发布授权`}
          busy={busy}
          onClose={() => {
            setOpen(false);
            setRevokeId("");
          }}
        >
          <p>
            家人分享通过链接访问，任何获得链接的人都能观看，请仅发送给信任的家人。
          </p>
          <p>
            撤回发布或撤销有效授权后，链接将停止新的访问；已下载或保存的副本无法收回。
          </p>
          <QueryState queries={[consents]} loadingText="正在读取授权……" />
          {!consents.isPending && !consents.isError && (
            <>
              {grants.length ? (
                <div className="min-w-0 space-y-3">
                  <p>现有有效授权（同一人物的其他发布也可能使用这些授权）：</p>
                  {grants.map((grant) => (
                    <div
                      key={grant.id}
                      className="flex flex-wrap items-center gap-3"
                    >
                      <span className="min-w-0 break-all">
                        {grant.granted_by} ·{" "}
                        {grant.scope === "family"
                          ? "家人范围"
                          : grant.scope === "friends"
                            ? "朋友范围"
                            : "公开范围"}
                      </span>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() => setRevokeId(grant.id)}
                      >
                        撤销这份授权
                      </Button>
                    </div>
                  ))}
                  {revokeId && (
                    <div role="alert" className="notice">
                      <p>
                        确认撤销这份授权？没有其他有效授权覆盖的分享链接将停止访问。重新授权需要重新发布。
                      </p>
                      <Button
                        variant="destructive"
                        disabled={busy}
                        onClick={() => revoke.mutate(revokeId)}
                      >
                        确认撤销
                      </Button>{" "}
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() => setRevokeId("")}
                      >
                        取消撤销
                      </Button>
                    </div>
                  )}
                </div>
              ) : (
                <label className="grid gap-2">
                  {person.is_minor ? "监护人姓名" : "授权人姓名"}
                  <Input
                    value={grantor}
                    maxLength={120}
                    disabled={busy}
                    onChange={(event) => setGrantor(event.target.value)}
                  />
                </label>
              )}
              {!publication && (
                <>
                  <label className="flex items-start gap-3 py-3">
                    <input
                      type="checkbox"
                      checked={confirmed}
                      disabled={busy}
                      onChange={(event) => setConfirmed(event.target.checked)}
                    />
                    <span>
                      {grants.length
                        ? "我确认本次分享仍在上述有效授权范围内。"
                        : person.is_minor
                          ? "我已获得监护人同意，允许将这位家人的影像通过链接分享给家人。"
                          : "我本人同意，或已获得本人同意，将影像通过链接分享给家人。"}
                    </span>
                  </label>
                  <Button
                    disabled={
                      busy ||
                      !confirmed ||
                      (!grants.length && !grantor.trim()) ||
                      !!revokeId
                    }
                    onClick={() => publish.mutate()}
                  >
                    {publish.isPending ? "正在发布" : "确认授权并发布"}
                  </Button>
                </>
              )}
            </>
          )}
          <ErrorNotice error={publish.error || revoke.error} />
        </AccountDialog>
      )}
    </div>
  );
}
