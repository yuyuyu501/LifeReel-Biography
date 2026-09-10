import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export function RechargeDialog({
  children,
  onClose,
}: {
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement;
    document.body.style.overflow = "hidden";
    dialog.showModal();
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      className="recharge-dialog"
      aria-labelledby="payment-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="recharge-dialog-header">
        <h2 id="payment-dialog-title">微信扫码支付</h2>
        <button
          type="button"
          className="icon-button"
          title="关闭支付窗口"
          aria-label="关闭支付窗口"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </header>
      {children}
    </dialog>
  );
}
