"use client";

import { useEffect, useRef, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { ChatMessage } from "@/components/chat/chat-message";
import { ChatInput } from "@/components/chat/chat-input";
import { useSessions } from "@/components/session-context";
import type { ChatResponse, MessageOut, UsageSummary } from "@/lib/types";

const DISCLAIMER = "⚠️ Đây không phải lời khuyên đầu tư cá nhân hoá. Thông tin chỉ mang tính tham khảo.";
const SLOW_HINT_MS = 8000;

export default function ChatPage() {
  const { activeThreadId, refreshSessions } = useSessions();
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [slowHint, setSlowHint] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!activeThreadId) return;
    void loadThread(activeThreadId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThreadId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  async function loadThread(id: string) {
    try {
      const res = await fetch(`/api/sessions/${id}/history`);
      setMessages(res.ok ? await res.json() : []);
    } catch {
      setMessages([]);
    }
    void fetchUsage(id);
  }

  async function fetchUsage(id: string) {
    try {
      const res = await fetch(`/api/usage/${id}`);
      if (res.ok) setUsage(await res.json());
    } catch {
      // usage widget is a nice-to-have -- silently skip on failure
    }
  }

  async function sendMessage(text: string) {
    if (!activeThreadId) return;
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);
    const slowTimer = setTimeout(() => setSlowHint(true), SLOW_HINT_MS);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: activeThreadId, message: text }),
      });
      if (res.status === 429) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "Bạn đã gửi quá nhiều tin nhắn trong 1 giờ qua, vui lòng thử lại sau." },
        ]);
        return;
      }
      if (!res.ok) {
        setMessages((prev) => [...prev, { role: "assistant", content: "Lỗi khi gọi backend, vui lòng thử lại." }]);
        return;
      }
      const data: ChatResponse = await res.json();
      setMessages((prev) => [...prev, { role: "assistant", content: data.answer }]);
      // Title may have just been auto-generated server-side on the first
      // message of a session -- refresh the sidebar list to pick it up.
      void refreshSessions();
      void fetchUsage(activeThreadId);
    } catch {
      setMessages((prev) => [...prev, { role: "assistant", content: "Không kết nối được backend, vui lòng thử lại." }]);
    } finally {
      clearTimeout(slowTimer);
      setSlowHint(false);
      setLoading(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <h1 className="text-lg font-semibold">Trợ lý chứng khoán Việt Nam</h1>
        {usage && (
          <div className="flex gap-4 text-xs text-muted-foreground">
            <span>
              Token vào/ra: <span className="font-medium text-foreground">{usage.tokens_in}</span>/
              <span className="font-medium text-foreground">{usage.tokens_out}</span>
            </span>
            <span>
              Lượt gọi: <span className="font-medium text-foreground">{usage.calls}</span>
            </span>
          </div>
        )}
      </header>
      <ScrollArea className="min-h-0 flex-1" viewportRef={scrollRef}>
        <div className="mx-auto max-w-3xl px-6 py-2">
          {messages.length === 0 && !loading && (
            <p className="py-16 text-center text-sm text-muted-foreground">
              Hỏi về mã cổ phiếu, giá, hồ sơ doanh nghiệp, chỉ báo kỹ thuật, tin tức, BCTC, hoặc yêu cầu đánh giá
              công ty để bắt đầu.
            </p>
          )}
          {messages.map((m, i) => (
            <ChatMessage key={i} message={m} />
          ))}
          {loading && (
            <div className="flex gap-3 py-3">
              <Skeleton className="h-8 w-8 shrink-0 rounded-full" />
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
                {slowHint && (
                  <p className="text-xs text-muted-foreground">
                    Câu hỏi này có thể cần tra nhiều nguồn dữ liệu, đang xử lý (thường mất 10-20 giây)...
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      </ScrollArea>
      <div className="mx-auto w-full max-w-3xl">
        <ChatInput disabled={loading || !activeThreadId} onSend={sendMessage} />
        <p className="px-3 pb-2 text-center text-xs text-muted-foreground">{DISCLAIMER}</p>
      </div>
    </div>
  );
}
