import { X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog";

export function RechargeDialog({
  children,
  onClose,
}: {
  children: ReactNode;
  onClose: () => void;
}) {
  const [previousFocus] = useState(() => document.activeElement);
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent
        aria-describedby={undefined}
        showCloseButton={false}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (previousFocus instanceof HTMLElement) previousFocus.focus();
        }}
      >
        <DialogHeader className="flex-row items-center justify-between text-left">
          <DialogTitle>微信扫码支付</DialogTitle>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="关闭支付窗口"
            aria-label="关闭支付窗口"
            onClick={onClose}
          >
            <X size={20} />
          </Button>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}
