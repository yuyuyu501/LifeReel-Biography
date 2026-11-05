import { request } from "./client";

export type BookRevision = {
  id: string;
  version_number: number;
  title: string;
  body: string;
  word_count: number;
  source_claim_ids: string[];
  author: string;
  generation_model: string | null;
  created_at: string;
};
export type BookChapter = {
  source_entry_ids?: string[];
  id: string;
  chapter_id: string;
  title: string;
  order_index: number;
  version_number: number;
  status: string;
  source_count: number;
  stale: boolean;
  job_id: string | null;
  error_code: string | null;
  missing_details?: string[];
  validation_reason?: string | null;
  current: BookRevision | null;
};
export type Book = {
  profile_id?: string | null;
  directory_version?: number;
  id: string;
  subject_id: string;
  title: string;
  target_words: number;
  chapters: BookChapter[];
  archived_chapters?: BookChapter[];
};
export type BookGeneration = {
  idempotency_key: string;
  chapter_ids?: string[];
  overwrite?: boolean;
  missing_only?: boolean;
  expected_versions?: Record<string, number>;
};
export type BookFactCheckEvidence = {
  kind: "source" | "chapter";
  chapter_id: string;
  chapter_title: string;
  quote: string;
  claim_id: string | null;
  revision_id: string | null;
  version_number: number | null;
};
export type BookFactCheckFinding = {
  id: string;
  type: "conflict" | "unsupported" | "cross_chapter";
  chapter_id: string;
  chapter_title: string;
  quote: string;
  quote_location: "body" | "title";
  quote_position: number;
  explanation: string;
  evidence: BookFactCheckEvidence[];
  review_status: "pending" | "false_positive";
};
export type BookFactCheckSnapshotChapter = {
  chapter_id: string;
  chapter_title: string;
  revision_id: string;
  version_number: number;
  source_digest: string;
};
export type BookFactCheck = {
  id: string;
  job_id: string | null;
  status: "queued" | "running" | "completed" | "failed" | "stale";
  stale: boolean;
  chapters_checked: number;
  snapshot_chapters: BookFactCheckSnapshotChapter[];
  findings: BookFactCheckFinding[];
  error_code: string | null;
  created_at: string;
  updated_at: string;
};
export const booksApi = {
  directory: (
    id: string,
    data: {
      expected_version: number;
      title: string;
      chapters: {
        id?: string;
        title: string;
        source_entry_ids: string[];
      }[];
    },
  ) =>
    request<Book>(`/v1/books/${id}/directory`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  list: () => request<Book[]>("/v1/books"),
  create: (data: { subject_id: string; title?: string }) =>
    request<Book>("/v1/books", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  read: (id: string) => request<Book>("/v1/books/" + id),
  generate: (id: string, data: BookGeneration) =>
    request<{
      job_ids: string[];
      skipped_chapter_ids: string[];
    }>("/v1/books/" + id + "/generate", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  edit: (
    id: string,
    chapterId: string,
    data: {
      expected_version: number;
      title: string;
      body: string;
      confirm_profile_version?: number;
    },
  ) =>
    request<Book>("/v1/books/" + id + "/chapters/" + chapterId, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  history: (id: string, chapterId: string) =>
    request<BookRevision[]>(
      "/v1/books/" + id + "/chapters/" + chapterId + "/versions",
    ),
  queueFactCheck: (id: string, idempotencyKey: string) =>
    request<BookFactCheck>(`/v1/books/${id}/fact-checks`, {
      method: "POST",
      body: JSON.stringify({ idempotency_key: idempotencyKey }),
    }),
  latestFactCheck: (id: string) =>
    request<BookFactCheck | null>(`/v1/books/${id}/fact-checks/latest`),
  factCheck: (id: string, checkId: string) =>
    request<BookFactCheck>(`/v1/books/${id}/fact-checks/${checkId}`),
  reviewFactCheckFinding: (id: string, checkId: string, findingId: string) =>
    request<BookFactCheck>(
      `/v1/books/${id}/fact-checks/${checkId}/findings/${findingId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ status: "false_positive" }),
      },
    ),
};
