import { describe, expect, it } from "vitest";
import { providerLabel, statusLabel } from "./statusLabels";

describe("状态中文化", () => {
  it("覆盖业务状态和可见范围", () => {
    expect(statusLabel("granted")).toBe("已授权");
    expect(statusLabel("disputed")).toBe("存在争议");
    expect(statusLabel("family")).toBe("家人可见");
  });

  it("不会把未知英文状态直接显示给用户", () => {
    expect(statusLabel("provider_internal_state")).toBe("未知状态");
    expect(providerLabel("vendor-secret-name")).toBe("已配置生成服务");
  });
});
