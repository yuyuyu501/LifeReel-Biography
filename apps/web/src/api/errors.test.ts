import { describe, expect, it } from "vitest";
import { ApiError, apiErrorFromResponse, isApiError, workflowErrorContext } from "./errors";

describe("API 错误码本地化", () => {
  it.each([
    "EVIDENCE_TEXT_TOO_LARGE", "MEMORY_INPUT_TOO_LARGE", "SCRIPT_INPUT_TOO_LARGE",
    "SCRIPT_MOCK_OUTPUT_TOO_LARGE",
  ])("处理预算错误 %s 明确提示保留资料和调整输入", (code) => {
    const message = new ApiError(code, 413).message;
    expect(message).toContain("保留");
    expect(message).not.toContain("稍后重试");
    expect(message).not.toContain("操作失败");
  });
  it.each([504, 524])("区分服务商网关超时 %s，且不显示响应文本", (status) => {
    const error = apiErrorFromResponse(502, { error: {
      code: "INTERVIEW_LLM_REQUEST_FAILED",
      context: { provider_http_status: status, body: "PRIVATE-PROMPT" },
    } });
    expect(error.message).toContain("AI 服务商等待超时");
    expect(error.message).toContain("可能已产生费用");
    expect(error.message).not.toContain("PRIVATE-PROMPT");
  });

  it("刷新后的工作流仍显示网关超时原因", () => {
    const context = workflowErrorContext({ memory_recovery: { diagnostic: {
      provider_http_status: 524, provider_request_id: "req-123", body: "PRIVATE-PROMPT",
    } } });
    expect(context).toEqual({ provider_http_status: 524, provider_request_id: "req-123" });
    expect(new ApiError("INTERVIEW_LLM_REQUEST_FAILED", 500, context).message)
      .toContain("AI 服务商等待超时");
    expect(workflowErrorContext({})).toEqual({});
  });
  it("把后端错误码转换为中文", () => {
    const error = apiErrorFromResponse(401, {
      error: { code: "AUTH_INVALID_CREDENTIALS" },
    });

    expect(error.code).toBe("AUTH_INVALID_CREDENTIALS");
    expect(error.message).toBe("账号或密码不正确，或账号已停用。");
    expect(isApiError(error, "AUTH_INVALID_CREDENTIALS")).toBe(true);
  });

  it("未知错误码不会显示后端英文内容", () => {
    const error = apiErrorFromResponse(500, {
      error: { code: "UNKNOWN_PROVIDER_MESSAGE", context: { detail: "English failure" } },
    });

    expect(error.message).toBe("操作失败，请稍后重试。");
    expect(error.message).not.toContain("English");
  });

  it("网络错误使用中文提示", () => {
    expect(new ApiError("NETWORK_ERROR", 0).message).toBe("网络连接失败，请检查网络后重试。");
  });

  it("AI 工作流错误提示用户稍后重试", () => {
    expect(new ApiError("INTERVIEW_LLM_REQUEST_FAILED", 502).message).toContain("等待片刻后重试");
    expect(new ApiError("MEMORY_LLM_REQUEST_FAILED", 502).message).toContain("稍后重试");
  });

  it("前端校验也使用错误码映射", () => {
    const error = new ApiError("EVIDENCE_ASSET_REQUIRED", 400);
    expect(error.code).toBe("EVIDENCE_ASSET_REQUIRED");
    expect(error.message).toBe("请先选择一份素材。");
  });

  it("根据错误上下文显示对应类型的上传上限", () => {
    const error = new ApiError("EVIDENCE_FILE_TOO_LARGE", 413, {
      kind: "video",
      limit_bytes: 2 * 1024 ** 3,
    });

    expect(error.message).toBe("视频不能超过 2 GB。");
  });
});
