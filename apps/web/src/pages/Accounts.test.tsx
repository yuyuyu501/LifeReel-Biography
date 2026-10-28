import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, vi } from "vitest";
import { api } from "../api/client";
import { ApiError } from "../api/errors";
import { LoginPage } from "./LoginPage";
import { AccountPage } from "./AccountPage";
import { AccountsAdminPage } from "./AccountsAdminPage";
import { SmsCodeField } from "../components/SmsCodeField";

const user = {
  id: "user-1",
  tenant_id: "tenant-1",
  email: null,
  phone: "13800138001",
  display_name: "测试用户",
  role: "owner",
  is_admin: false,
};
const account = {
  ...user,
  created_at: "2026-09-15T10:00:00Z",
  deleted_at: null,
  is_active: true,
};

beforeEach(() => {
  vi.restoreAllMocks();
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  vi.spyOn(api, "registration").mockResolvedValue({
    enabled: true,
    sms_enabled: true,
    password_reset_enabled: true,
    phone_verification_enabled: true,
  });
  vi.spyOn(api, "sendSms").mockResolvedValue({
    challenge_id: "challenge-1",
    expires_in: 300,
    retry_after: 60,
  });
  vi.spyOn(api, "me").mockResolvedValue(user);
});

function renderPage(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<h1>已进入工作台</h1>} />
          <Route path="/login" element={<LoginPage key="login" />} />
          <Route path="/register" element={<LoginPage key="register" />} />
          <Route path="/forgot-password" element={<LoginPage key="reset" />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/admin/accounts" element={<AccountsAdminPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("registers with verified phone and opens the workspace", async () => {
  const register = vi.spyOn(api, "register").mockResolvedValue(user);
  vi.spyOn(api, "login").mockResolvedValue({ user, expires_in: 3600 });
  renderPage("/register");
  fireEvent.change(screen.getByLabelText("称呼"), {
    target: { value: "新家人" },
  });
  fireEvent.change(screen.getByLabelText("手机号"), {
    target: { value: user.phone },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "获取验证码" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "获取验证码" }));
  await screen.findByText("验证码已发送，请查看手机短信。");
  expect(screen.getByRole("button", { name: "60秒后重发" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("短信验证码"), {
    target: { value: "123456" },
  });
  fireEvent.change(screen.getByLabelText("密码", { exact: true }), {
    target: { value: "Password123!" },
  });
  fireEvent.change(screen.getByLabelText("确认密码"), {
    target: { value: "Password123!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "注册并进入" }));
  await screen.findByRole("heading", { name: "已进入工作台" });
  expect(register).toHaveBeenCalledWith({
    phone: user.phone,
    challenge_id: "challenge-1",
    code: "123456",
    display_name: "新家人",
    password: "Password123!",
  });
});

test("preserves successful signup if automatic login fails", async () => {
  vi.spyOn(api, "register").mockResolvedValue(user);
  vi.spyOn(api, "login").mockRejectedValue(new Error("network"));
  renderPage("/register");
  fireEvent.change(screen.getByLabelText("称呼"), {
    target: { value: "新家人" },
  });
  fireEvent.change(screen.getByLabelText("手机号"), {
    target: { value: user.phone },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "获取验证码" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "获取验证码" }));
  await screen.findByText("验证码已发送，请查看手机短信。");
  fireEvent.change(screen.getByLabelText("短信验证码"), {
    target: { value: "123456" },
  });
  for (const label of ["密码", "确认密码"]) {
    fireEvent.change(screen.getByLabelText(label, { exact: true }), {
      target: { value: "Password123!" },
    });
  }
  fireEvent.click(screen.getByRole("button", { name: "注册并进入" }));
  await screen.findByRole("heading", { name: "登录后继续整理" });
  expect(await screen.findByRole("status")).toHaveTextContent("账号已注册成功");
  expect(screen.getByLabelText("手机号或邮箱")).toHaveValue(user.phone);
  expect(screen.getByLabelText("密码", { exact: true })).toHaveValue("");
  expect(api.register).toHaveBeenCalledOnce();
});

test("rejects mismatched passwords without calling registration", async () => {
  const register = vi.spyOn(api, "register");
  renderPage("/register");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "注册并进入" })).toBeEnabled(),
  );
  fireEvent.change(screen.getByLabelText("密码", { exact: true }), {
    target: { value: "Password123!" },
  });
  fireEvent.change(screen.getByLabelText("确认密码"), {
    target: { value: "Different123!" },
  });
  fireEvent.submit(
    screen.getByRole("button", { name: "注册并进入" }).closest("form")!,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "两次输入的密码不一致",
  );
  expect(register).not.toHaveBeenCalled();
});

test("shows disabled SMS configuration without an enabled register button", async () => {
  vi.spyOn(api, "registration").mockResolvedValue({
    enabled: true,
    sms_enabled: false,
  });
  renderPage("/register");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "短信验证暂未开通",
  );
  expect(screen.getByRole("button", { name: "注册并进入" })).toBeDisabled();
});

test("keeps registration discoverable when it is disabled on the server", async () => {
  vi.spyOn(api, "registration").mockResolvedValue({
    enabled: false,
    sms_enabled: true,
  });
  renderPage("/login");
  fireEvent.click(screen.getByRole("link", { name: "注册新账号" }));
  expect(await screen.findByText("注册暂未开放，请联系管理员。")).toBeVisible();
  expect(screen.getByRole("button", { name: "注册并进入" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "获取验证码" })).toBeDisabled();
});

test("offers recovery when registration settings fail to load", async () => {
  vi.spyOn(api, "registration")
    .mockRejectedValueOnce(new Error("network"))
    .mockResolvedValue({
      enabled: true,
      sms_enabled: true,
    });
  renderPage("/register");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "无法读取账号服务状态",
  );
  expect(screen.getByRole("button", { name: "注册并进入" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "注册并进入" })).toBeEnabled(),
  );
});

test("guides an unregistered phone from recovery to signup without reusing verification", async () => {
  vi.spyOn(api, "resetPassword").mockRejectedValue(
    new ApiError("AUTH_PHONE_NOT_REGISTERED", 400),
  );
  renderPage("/forgot-password");
  fireEvent.change(screen.getByLabelText("手机号"), {
    target: { value: user.phone },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "获取验证码" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "获取验证码" }));
  await screen.findByText("验证码已发送，请查看手机短信。");
  fireEvent.change(screen.getByLabelText("短信验证码"), {
    target: { value: "123456" },
  });
  for (const label of ["新密码", "确认密码"]) {
    fireEvent.change(screen.getByLabelText(label, { exact: true }), {
      target: { value: "Password123!" },
    });
  }
  fireEvent.click(screen.getByRole("button", { name: "重置密码" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "该手机号尚未注册",
  );
  fireEvent.click(screen.getByRole("link", { name: "注册新账号" }));
  expect(
    await screen.findByRole("heading", { name: "创建家庭账户" }),
  ).toBeVisible();
  expect(screen.getByLabelText("手机号")).toHaveValue(user.phone);
  expect(screen.getByLabelText("短信验证码")).toHaveValue("");
  expect(screen.getByLabelText("密码", { exact: true })).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "获取验证码" }));
  await waitFor(() =>
    expect(api.sendSms).toHaveBeenLastCalledWith(user.phone, "register"),
  );
});

test("resets password with a purpose-bound SMS and returns to login", async () => {
  const reset = vi.spyOn(api, "resetPassword").mockResolvedValue(undefined);
  renderPage("/forgot-password");
  fireEvent.change(screen.getByLabelText("手机号"), {
    target: { value: user.phone },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "获取验证码" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "获取验证码" }));
  await screen.findByText("验证码已发送，请查看手机短信。");
  expect(api.sendSms).toHaveBeenCalledWith(user.phone, "reset_password");
  fireEvent.change(screen.getByLabelText("短信验证码"), {
    target: { value: "123456" },
  });
  fireEvent.change(screen.getByLabelText("新密码", { exact: true }), {
    target: { value: "Password123!" },
  });
  fireEvent.change(screen.getByLabelText("确认密码"), {
    target: { value: "Password123!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "重置密码" }));
  await screen.findByRole("heading", { name: "登录后继续整理" });
  expect(reset).toHaveBeenCalledOnce();
  expect(screen.getByRole("status")).toHaveTextContent("密码已重置");
});

test("SMS failure gives a Chinese error and allows retry", async () => {
  const onChange = vi.fn();
  vi.spyOn(api, "sendSms").mockRejectedValue(
    new Error("短信发送失败，请稍后再试。"),
  );
  render(
    <SmsCodeField phone={user.phone} purpose="register" onChange={onChange} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "获取验证码" }));
  await screen.findByRole("alert");
  expect(onChange).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "获取验证码" })).toBeEnabled();
});

test("account settings saves profile and requires re-login after password change", async () => {
  vi.spyOn(api, "updateProfile").mockResolvedValue({
    ...user,
    display_name: "修改称呼",
  });
  const change = vi.spyOn(api, "changePassword").mockResolvedValue(undefined);
  renderPage("/account");
  fireEvent.change(await screen.findByLabelText("称呼"), {
    target: { value: "修改称呼" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存资料" }));
  await screen.findByText("资料已保存。");
  fireEvent.change(screen.getAllByLabelText("当前密码")[0], {
    target: { value: "Password123!" },
  });
  fireEvent.change(screen.getByLabelText("新密码", { exact: true }), {
    target: { value: "NewPass123!" },
  });
  fireEvent.change(screen.getByLabelText("确认新密码"), {
    target: { value: "NewPass123!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "更新密码" }));
  await screen.findByRole("heading", { name: "登录后继续整理" });
  expect(change).toHaveBeenCalledWith("Password123!", "NewPass123!");
});

test("admin account list supports search edit disable and delete confirmation", async () => {
  const list = vi
    .spyOn(api, "accounts")
    .mockResolvedValue({ items: [account], total: 1, page: 1, page_size: 20 });
  const update = vi
    .spyOn(api, "updateAccount")
    .mockResolvedValue({ ...account, is_active: false });
  const remove = vi.spyOn(api, "removeAccount").mockResolvedValue(undefined);
  renderPage("/admin/accounts");
  await screen.findByText(user.display_name);
  fireEvent.change(screen.getByLabelText("搜索账号"), {
    target: { value: "测试" },
  });
  fireEvent.click(screen.getByRole("button", { name: "搜索" }));
  await waitFor(() => expect(list).toHaveBeenCalledWith("测试", "all", 1));
  fireEvent.click(await screen.findByRole("button", { name: "编辑 测试用户" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByLabelText("允许登录"));
  fireEvent.click(within(dialog).getByRole("button", { name: "保存账号" }));
  await waitFor(() =>
    expect(update).toHaveBeenCalledWith(user.id, {
      display_name: user.display_name,
      is_active: false,
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole("button", { name: "删除 测试用户" }));
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(remove).toHaveBeenCalledWith(user.id));
});

test("admin create and protected administrator controls", async () => {
  vi.spyOn(api, "accounts").mockResolvedValue({
    items: [{ ...account, is_admin: true }],
    total: 1,
    page: 1,
    page_size: 20,
  });
  const create = vi.spyOn(api, "createAccount").mockResolvedValue(account);
  renderPage("/admin/accounts");
  await screen.findByText(user.display_name);
  expect(screen.getByRole("button", { name: "删除 测试用户" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "新增账号" }));
  const dialog = within(screen.getByRole("dialog"));
  fireEvent.change(dialog.getByLabelText("称呼"), {
    target: { value: "新账号" },
  });
  fireEvent.change(dialog.getByLabelText("邮箱"), {
    target: { value: "new@example.com" },
  });
  fireEvent.change(dialog.getByLabelText("初始密码"), {
    target: { value: "Password123!" },
  });
  fireEvent.click(dialog.getByRole("button", { name: "保存账号" }));
  await waitFor(() =>
    expect(create).toHaveBeenCalledWith({
      display_name: "新账号",
      email: "new@example.com",
      password: "Password123!",
    }),
  );
});

test("account page exposes sign-out on mobile without the sidebar", async () => {
  const logout = vi.spyOn(api, "logout").mockResolvedValue(undefined);
  renderPage("/account");
  fireEvent.click(await screen.findByRole("button", { name: "退出登录" }));
  await screen.findByRole("heading", { name: "登录后继续整理" });
  expect(logout).toHaveBeenCalledOnce();
});
