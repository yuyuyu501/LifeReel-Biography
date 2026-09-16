import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef, useState } from "react";
import { Button } from "./button";
import { Input } from "./input";
import { AccountDialog } from "../AccountDialog";

test("buttons preserve form submission and disabled semantics", () => {
  const submit = vi.fn((event) => event.preventDefault());
  render(
    <form onSubmit={submit}>
      <Button>保存</Button>
      <Button disabled>不可用</Button>
    </form>,
  );
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  expect(submit).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "不可用" }));
  expect(submit).toHaveBeenCalledTimes(1);
});

test("asChild preserves link navigation without nesting interactive controls", () => {
  render(
    <Button asChild variant="outline">
      <a href="/scripts">剧本</a>
    </Button>,
  );
  expect(screen.getByRole("link", { name: "剧本" })).toHaveAttribute(
    "href",
    "/scripts",
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

test("inputs preserve refs and browser password manager attributes", () => {
  const ref = createRef<HTMLInputElement>();
  render(
    <label>
      密码
      <Input ref={ref} type="password" autoComplete="new-password" required />
    </label>,
  );
  expect(ref.current).toBe(screen.getByLabelText("密码"));
  expect(ref.current).toHaveAttribute("autocomplete", "new-password");
  expect(ref.current).toBeRequired();
});

test("account dialogs isolate background and restore keyboard focus on Escape", async () => {
  function Harness() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <Button onClick={() => setOpen(true)}>编辑资料</Button>
        {open && (
          <AccountDialog title="资料" onClose={() => setOpen(false)}>
            <Input aria-label="称呼" />
          </AccountDialog>
        )}
      </>
    );
  }
  render(<Harness />);
  const trigger = screen.getByRole("button", { name: "编辑资料" });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "资料" });
  expect(
    screen.queryByRole("button", { name: "编辑资料" }),
  ).not.toBeInTheDocument();
  fireEvent.keyDown(dialog, { key: "Escape" });
  await waitFor(() => expect(trigger).toHaveFocus());
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("pending account mutations cannot be dismissed", () => {
  const close = vi.fn();
  render(
    <AccountDialog title="保存中" busy onClose={close}>
      <p>正在保存</p>
    </AccountDialog>,
  );
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(screen.getByRole("button", { name: "关闭窗口" })).toBeDisabled();
  expect(close).not.toHaveBeenCalled();
});
