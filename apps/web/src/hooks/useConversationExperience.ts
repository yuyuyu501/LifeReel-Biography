import { useEffect, useLayoutEffect, useRef, useState } from "react";

export function useInterviewDraft(sessionId: string) {
  const key = "lifereel:draft:" + sessionId;
  const [text, setText] = useState(() => {
    try {
      return sessionStorage.getItem(key) ?? "";
    } catch {
      return "";
    }
  });
  useEffect(() => {
    try {
      if (text) sessionStorage.setItem(key, text);
      else sessionStorage.removeItem(key);
    } catch {
      /* Browser may disable storage; do not block typing. */
    }
  }, [key, text]);
  return [text, setText] as const;
}

export function useConversationFollow(messageKey: string) {
  const conversation = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const [unread, setUnread] = useState(false);
  const previous = useRef("");
  useLayoutEffect(() => {
    const element = conversation.current;
    if (!element || messageKey === previous.current) return;
    previous.current = messageKey;
    if (following.current) element.scrollTop = element.scrollHeight;
    else setUnread(true);
  }, [messageKey]);
  function onScroll() {
    const element = conversation.current;
    if (!element) return;
    following.current =
      element.scrollHeight - element.clientHeight - element.scrollTop < 96;
    if (following.current) setUnread(false);
  }
  function showLatest() {
    const element = conversation.current;
    if (element) element.scrollTop = element.scrollHeight;
    following.current = true;
    setUnread(false);
  }
  return { conversation, unread, onScroll, showLatest };
}
