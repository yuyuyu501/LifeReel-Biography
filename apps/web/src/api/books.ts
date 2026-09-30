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
  current: BookRevision | null;
};
export type Book = {
  id: string;
  subject_id: string;
  title: string;
  target_words: number;
  chapters: BookChapter[];
};
export type BookGeneration = {
  idempotency_key: string;
  chapter_ids?: string[];
  overwrite?: boolean;
  expected_versions?: Record<string, number>;
};
export const booksApi = {
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
    data: { expected_version: number; title: string; body: string },
  ) =>
    request<Book>("/v1/books/" + id + "/chapters/" + chapterId, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  history: (id: string, chapterId: string) =>
    request<BookRevision[]>(
      "/v1/books/" + id + "/chapters/" + chapterId + "/versions",
    ),
};
