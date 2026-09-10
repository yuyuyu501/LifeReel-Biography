import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";

afterEach(() => vi.unstubAllGlobals());

const file = new File(["memory"], "memory.txt", { type: "text/plain" });
const payload = { subjectId: "person-1", interviewSessionId: "session-1",
  kind: "document" as const, file };
const json = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200, headers: { "Content-Type": "application/json" },
});

describe("evidence direct upload", () => {
  it("uploads bytes only to OSS, then confirms the permit", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({ direct_upload: true }))
      .mockResolvedValueOnce(json({ upload_id: "upload-1",
        url: "https://test.oss-cn-shenzhen.aliyuncs.com",
        fields: { key: "scoped/file", policy: "signed" } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(json({ id: "asset-1" }));
    vi.stubGlobal("fetch", fetcher);
    expect(await api.uploadEvidence(payload)).toEqual({ id: "asset-1" });
    const request = JSON.parse(fetcher.mock.calls[1][1].body);
    expect(request.subject_id).toBe("person-1");
    expect(request.interview_session_id).toBe("session-1");
    expect(request.byte_size).toBe(6);
    const direct = fetcher.mock.calls[2];
    expect(direct[0]).toBe("https://test.oss-cn-shenzhen.aliyuncs.com");
    expect(direct[1].credentials).toBe("omit");
    expect(direct[1].headers).toBeUndefined();
    expect(Array.from(direct[1].body.keys()).at(-1)).toBe("file");
    expect(JSON.parse(fetcher.mock.calls[3][1].body)).toEqual({ upload_id: "upload-1" });
  });

  it("does not confirm or silently proxy when OSS rejects the file", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({ direct_upload: true }))
      .mockResolvedValueOnce(json({ upload_id: "upload-1", url: "https://oss.example",
        fields: {} }))
      .mockResolvedValueOnce(new Response("private vendor XML", { status: 403 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(api.uploadEvidence(payload)).rejects.toMatchObject({ code: "EVIDENCE_UPLOAD_FAILED" });
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("reports a CORS or network failure as a localized error code", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(json({ direct_upload: true }))
      .mockResolvedValueOnce(json({ upload_id: "upload-1", url: "https://oss.example", fields: {} }))
      .mockRejectedValueOnce(new TypeError("Failed to fetch")));
    await expect(api.uploadEvidence(payload)).rejects.toMatchObject({ code: "EVIDENCE_UPLOAD_FAILED" });
  });

  it("keeps the local storage fallback only when direct upload is disabled", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json({ direct_upload: false }))
      .mockResolvedValueOnce(json({ id: "local-1" }));
    vi.stubGlobal("fetch", fetcher);
    expect(await api.uploadEvidence(payload)).toEqual({ id: "local-1" });
    expect(fetcher.mock.calls[1][0]).toBe("/v1/evidence/assets");
    expect(fetcher.mock.calls[1][1].body.get("file")).toBe(file);
  });
});
