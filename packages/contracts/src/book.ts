export interface BookRevision {
  id: string;
  version_number: number;
  title: string;
  body: string;
  word_count: number;
  source_claim_ids: string[];
  author: string;
  generation_model: string | null;
  created_at: string;
}
export interface BookChapter {
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
  source_entry_ids: string[];
}
export interface Book {
  id: string;
  subject_id: string;
  title: string;
  target_words: number;
  chapters: BookChapter[];
  archived_chapters?: BookChapter[];
  profile_id: string | null;
  directory_version: number;
}
