import type { LifeProfile, ProfileChange } from "@lifereel/contracts";
import { request, API_BASE_URL } from "./client";

export const profilesApi = {
  subject: (id: string) =>
    request<LifeProfile>(`/v1/life-profiles/subjects/${id}`),
  read: (id: string) => request<LifeProfile>(`/v1/life-profiles/${id}`),
  patch: (
    id: string,
    expected_version: number,
    changes: ProfileChange[],
    request_id: string,
  ) =>
    request<LifeProfile>(`/v1/life-profiles/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ expected_version, changes, request_id }),
    }),
  history: (id: string) =>
    request<
      Array<{
        version_number: number;
        actor: string;
        created_at: string;
        changes: Array<{ before?: unknown; after?: unknown }>;
      }>
    >(`/v1/life-profiles/${id}/history`),
  exportUrl: (id: string, format: "md" | "xlsx", includePrivate = false) =>
    `${API_BASE_URL}/v1/life-profiles/${id}/export?format=${format}&include_private=${includePrivate}`,
};
