import { useEffect, useId, useRef, useState } from "react";
import { api, type SmsPurpose, type SmsVerification } from "../api/client";

export function SmsCodeField({
  phone,
  purpose,
  onChange,
  disabled = false,
}: {
  phone: string;
  purpose: SmsPurpose;
  onChange: (value: SmsVerification) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const [challenge, setChallenge] = useState("");
  const [code, setCode] = useState("");
  const [remaining, setRemaining] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    const timer = window.setInterval(
      () => setRemaining((value) => Math.max(0, value - 1)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, []);
  async function send() {
    setPending(true);
    setError("");
    setSent(false);
    try {
      const result = await api.sendSms(phone, purpose);
      if (!mounted.current) return;
      setChallenge(result.challenge_id);
      setCode("");
      setRemaining(result.retry_after);
      setSent(true);
      onChange({ phone, challenge_id: result.challenge_id, code: "" });
    } catch (cause) {
      if (mounted.current)
        setError(
          cause instanceof Error ? cause.message : "短信发送失败，请稍后再试。",
        );
    } finally {
      if (mounted.current) setPending(false);
    }
  }
  return (
    <div className="sms-field">
      <label htmlFor={id}>短信验证码</label>
      <div className="sms-controls">
        <input
          id={id}
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={6}
          required
          value={code}
          disabled={disabled}
          aria-describedby={`${id}-feedback`}
          onChange={(event) => {
            const value = event.target.value;
            setCode(value);
            onChange({ phone, challenge_id: challenge, code: value });
          }}
        />
        <button
          type="button"
          className="button secondary"
          onClick={send}
          disabled={
            disabled || pending || remaining > 0 || !/^1[3-9]\d{9}$/.test(phone)
          }
        >
          {pending
            ? "正在发送"
            : remaining
              ? `${remaining}秒后重发`
              : "获取验证码"}
        </button>
      </div>
      <div id={`${id}-feedback`}>
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        {sent && !error && (
          <p className="field-success" role="status">
            验证码已发送，请查看手机短信。
          </p>
        )}
      </div>
    </div>
  );
}
