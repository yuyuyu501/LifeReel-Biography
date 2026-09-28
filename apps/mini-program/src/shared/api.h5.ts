// Browser previews are deliberately offline. Native builds resolve api.ts.
import type { miniApi as nativeApi } from "./api";
import type {
  Person,
  InterviewSession,
  ScriptProject,
  ProductionRun,
  MemoryClaim,
} from "@lifereel/contracts";

const stamp = () => new Date().toISOString();
let sequence = 0;
const id = (kind: string) => `preview-${kind}-${++sequence}`;
const user = {
  id: "preview-user",
  tenant_id: "preview-tenant",
  email: null,
  phone: null,
  display_name: "预览体验者",
  role: "owner",
  is_admin: false,
};
const auth = () => ({
  access_token: "preview-only",
  refresh_token: "preview-only",
  expires_in: 3600,
  user: { ...user },
});
let signedIn = true;
const people: Person[] = [
  {
    id: "preview-person",
    tenant_id: user.tenant_id,
    display_name: "林远（示例人物）",
    preferred_name: null,
    birth_year: 1965,
    birthplace: "广州（示例）",
    relation_to_owner: null,
    is_subject: true,
    biography_note: "虚构演示资料，仅保存在当前浏览器页面内存中",
    is_minor: false,
    guardian_name: null,
    created_at: stamp(),
    updated_at: stamp(),
  },
];
const chapters = [
  {
    id: "preview-childhood",
    order_index: 1,
    title: "童年与故乡",
    description: "从老街、院子和家人的声音开始",
    opening_questions: ["小时候住的地方是什么样的？"],
    is_system: true,
  },
  {
    id: "preview-school",
    order_index: 2,
    title: "求学与成长",
    description: "记下求学路上值得珍藏的片段",
    opening_questions: ["第一次上学时发生了什么？"],
    is_system: true,
  },
];
const sessions: InterviewSession[] = [];
const claims: MemoryClaim[] = [
  {
    id: "preview-claim",
    subject_id: people[0].id,
    interview_session_id: null,
    source_round_id: null,
    source_observation_id: null,
    chapter_id: chapters[0].id,
    claim_text: "1972 年开始上小学（虚构示例）",
    source_quote: "那年我七岁，沿着老街走到学校。",
    claim_type: "event",
    confidence: 1,
    review_status: "reviewed",
    extraction_provider: "local_preview",
    extraction_model: null,
    created_at: stamp(),
    updated_at: stamp(),
  },
];
const projects: ScriptProject[] = [
  {
    id: "preview-script",
    subject_id: people[0].id,
    title: "老街上的第一天（示例剧本）",
    mode: "single_chapter",
    status: "draft",
    audience: "private",
    source_claim_ids: [claims[0].id],
    version_number: 1,
    generation_provider: "local_preview",
    generation_model: null,
    created_at: stamp(),
    updated_at: stamp(),
    scenes: [
      {
        id: "preview-scene",
        chapter_id: chapters[0].id,
        order_index: 1,
        heading: "清晨 · 老街",
        plot: "一个孩子背着书包走向学校，镜头跟随脚步和沿路景物。",
        narration: "那是我第一次自己走去学校。",
        visual_prompt: "石板路、旧书包、晨光，只拍背影与物件。",
        duration_seconds: 10,
        source_claim_ids: [claims[0].id],
        visual_constraints: {
          face_policy: "no_identifiable_faces",
          required_elements: ["书包", "老街"],
          forbidden_elements: ["清晰正脸"],
          notes: "示例约束",
        },
        shots: [
          {
            id: "preview-shot-1",
            scene_id: "preview-scene",
            order_index: 1,
            shot_type: "特写",
            visual_prompt: "旧书包与握紧肩带的手，不出现人脸。",
            duration_seconds: 5,
            source_claim_ids: [claims[0].id],
          },
          {
            id: "preview-shot-2",
            scene_id: "preview-scene",
            order_index: 2,
            shot_type: "远景",
            visual_prompt: "晨光中的石板路与远去的背影，不出现可辨识人脸。",
            duration_seconds: 5,
            source_claim_ids: [claims[0].id],
          },
        ],
      },
    ],
    shots: [],
  },
];
const runs: ProductionRun[] = [];
function requireItem<T extends { id: string }>(items: T[], itemId: string): T {
  const item = items.find((value) => value.id === itemId);
  if (!item) throw new Error("预览资料不存在，请返回首页选择人物");
  return item;
}
async function unavailable(): Promise<never> {
  throw new Error("此能力需在开发者工具或真机测试，浏览器预览不调用外部服务");
}

export const miniApi: typeof nativeApi = {
  login: async (_platform, _code, displayName) => {
    user.display_name = displayName || "预览体验者";
    signedIn = true;
    return auth();
  },
  refresh: async () => {
    if (!signedIn) throw new Error("请先进入预览");
    return auth();
  },
  me: async () => {
    if (!signedIn) throw new Error("已退出预览，请从顶部重新进入");
    return { ...user };
  },
  saveAuth: () => {
    signedIn = true;
  },
  clearAuth: () => {
    signedIn = false;
  },
  persons: async () => [...people],
  person: async (personId) => requireItem(people, personId),
  createPerson: async (payload) => {
    const person: Person = {
      ...people[0],
      ...payload,
      id: id("person"),
      birth_year: payload.birth_year ?? null,
      birthplace: payload.birthplace ?? null,
      biography_note: "本地预览人物",
      created_at: stamp(),
      updated_at: stamp(),
    };
    people.push(person);
    return person;
  },
  updatePerson: async (personId, payload) =>
    Object.assign(requireItem(people, personId), payload, {
      updated_at: stamp(),
    }),
  chapters: async () => [...chapters],
  interviews: async () => [...sessions],
  startInterview: async (payload) => {
    requireItem(people, payload.subject_id);
    const session: InterviewSession = {
      ...payload,
      id: id("session"),
      chapter_id: payload.chapter_id || null,
      topic_hint: payload.topic_hint || null,
      status: "active",
      round_count: 0,
      started_at: stamp(),
      updated_at: stamp(),
      completed_at: null,
      rounds: [],
    };
    sessions.push(session);
    return session;
  },
  interview: async (sessionId) => requireItem(sessions, sessionId),
  nextQuestion: async (sessionId) => ({
    question_text: requireItem(sessions, sessionId).round_count
      ? "那段经历中，最让你难忘的细节是什么？（示例追问）"
      : "小时候住的地方是什么样的？（示例问题）",
    question_intent: "preview",
    question_source: "local_preview",
  }),
  createRound: async (sessionId, payload) => {
    const session = requireItem(sessions, sessionId);
    const round = {
      id: id("round"),
      round_index: session.rounds.length + 1,
      question_text: payload.question_text,
      question_intent: payload.question_intent || null,
      question_source: "local_preview",
      answer_text: null,
      source_asset_id: null,
      transcript_status: "not_required",
      created_at: stamp(),
      answered_at: null,
    };
    session.rounds.push(round);
    return round;
  },
  answerRound: async (sessionId, roundId, payload) => {
    const session = requireItem(sessions, sessionId);
    const round = requireItem(session.rounds, roundId);
    round.answer_text = payload.answer_text;
    round.answered_at = stamp();
    session.round_count = session.rounds.filter(
      (item) => item.answer_text !== null,
    ).length;
    return round;
  },
  createTurn: async (sessionId, payload) => {
    const session = requireItem(sessions, sessionId);
    const claim = {
      ...claims[0],
      id: id("claim"),
      subject_id: session.subject_id,
      interview_session_id: sessionId,
      source_round_id: payload.round_id || null,
      chapter_id: session.chapter_id,
      claim_text: payload.answer_text || "示例更新",
      source_quote: payload.answer_text || "",
      review_status: "unreviewed",
      created_at: stamp(),
      updated_at: stamp(),
    };
    claims.push(claim);
    return {
      id: id("workflow"),
      session_id: sessionId,
      round_id: payload.round_id || "",
      chapter_id: session.chapter_id,
      job_id: null,
      idempotency_key: payload.idempotency_key,
      status: "completed",
      asset_ids: [],
      source_claim_ids: [claim.id],
      script_scene_ids: [],
      script_project_id: null,
      next_question: "本地模拟已保存回答；未调用 AI，未生成真实剧本。",
      next_question_intent: null,
      missing_topics: [],
      script_brief: {},
      error_code: null,
      created_at: stamp(),
      updated_at: stamp(),
      completed_at: stamp(),
    };
  },
  workspace: async (sessionId) => ({
    session: requireItem(sessions, sessionId),
    assets: [],
    script: null,
    latest_workflow: null,
  }),
  memories: async (subjectId) =>
    claims.filter((item) => item.subject_id === subjectId),
  memoryOverview: async (subjectId) => ({
    claim_count: claims.filter((item) => item.subject_id === subjectId).length,
    reviewed_count: subjectId === people[0].id ? 1 : 0,
    entity_count: subjectId === people[0].id ? 1 : 0,
    timeline_count: subjectId === people[0].id ? 1 : 0,
    open_conflict_count: 0,
    covered_chapter_ids: [chapters[0].id],
    coverage_ratio: 0.5,
  }),
  entities: async (subjectId) =>
    subjectId === people[0].id
      ? [
          {
            id: "preview-place",
            subject_id: subjectId,
            entity_type: "place",
            name: "老街（示例）",
            relationship: "童年居住地",
            source_claim_ids: [claims[0].id],
          },
        ]
      : [],
  timeline: async (subjectId) =>
    subjectId === people[0].id
      ? [
          {
            id: "preview-date",
            subject_id: subjectId,
            claim_id: claims[0].id,
            year: 1972,
            time_text: "1972 年",
            event_text: "第一次上小学（虚构示例）",
            precision: "year",
          },
        ]
      : [],
  conflicts: async () => [],
  graph: async (subjectId) => ({ subject_id: subjectId, nodes: [], edges: [] }),
  scripts: async () => [...projects],
  script: async (projectId) => requireItem(projects, projectId),
  generateScript: async (payload) => {
    requireItem(people, payload.subject_id);
    const project = {
      ...projects[0],
      id: id("script"),
      subject_id: payload.subject_id,
      title: payload.title || "本地示例剧本（未调用 AI）",
      version_number:
        projects.filter((item) => item.subject_id === payload.subject_id)
          .length + 1,
      created_at: stamp(),
      updated_at: stamp(),
    };
    projects.unshift(project);
    return project;
  },
  productionSettings: async () => ({
    provider: "local_preview",
    model: null,
    resolution: null,
    ratio: null,
    duration_seconds: null,
    generate_audio: false,
  }),
  productionRuns: async () => [...runs],
  startProduction: async (payload) => {
    requireItem(projects, payload.project_id);
    const run: ProductionRun = {
      id: id("run"),
      project_id: payload.project_id,
      status: "预览示例：未实际生成视频",
      provider: "local_preview",
      audience: "private",
      estimated_cost: 0,
      actual_cost: 0,
      output_manifest: null,
      error_message: null,
      created_at: stamp(),
      updated_at: stamp(),
      assets: [],
    };
    runs.unshift(run);
    return run;
  },
  jobs: async () => [],
  job: unavailable,
  retryJob: unavailable,
  assets: async () => [],
  uploadAsset: unavailable,
};
