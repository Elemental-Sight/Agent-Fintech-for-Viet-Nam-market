"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { getCookie, setCookie } from "@/lib/client-cookie";
import type { SessionOut } from "@/lib/types";

const THREAD_COOKIE = "vn_agent_thread_id";

interface SessionsContextValue {
  sessions: SessionOut[];
  activeThreadId: string | null;
  refreshSessions: () => Promise<SessionOut[]>;
  createSession: () => Promise<void>;
  selectSession: (threadId: string) => void;
  deleteSession: (threadId: string) => Promise<void>;
  renameSession: (threadId: string, title: string) => Promise<void>;
  togglePin: (threadId: string) => Promise<void>;
}

const SessionsContext = createContext<SessionsContextValue | null>(null);

// Owns the session list + which thread is active so the sidebar (visible on
// every page) and the chat page (which loads that thread's messages) share
// one source of truth instead of drifting out of sync.
export function SessionsProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionOut[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const initialized = useRef(false);

  const refreshSessions = useCallback(async () => {
    const res = await fetch("/api/sessions");
    const data: SessionOut[] = await res.json();
    setSessions(data);
    return data;
  }, []);

  const createSession = useCallback(async () => {
    const res = await fetch("/api/sessions", { method: "POST" });
    const data = await res.json();
    setCookie(THREAD_COOKIE, data.thread_id);
    setActiveThreadId(data.thread_id);
    await refreshSessions();
    router.push("/chat");
  }, [refreshSessions, router]);

  const selectSession = useCallback(
    (threadId: string) => {
      setCookie(THREAD_COOKIE, threadId);
      setActiveThreadId(threadId);
      router.push("/chat");
    },
    [router]
  );

  const deleteSession = useCallback(
    async (threadId: string) => {
      try {
        await fetch(`/api/sessions/${threadId}`, { method: "DELETE" });
      } catch {
        toast.error("Không xóa được phiên.");
        return;
      }
      const list = await refreshSessions();
      if (threadId === activeThreadId) {
        if (list.length > 0) {
          selectSession(list[0].thread_id);
        } else {
          await createSession();
        }
      }
    },
    [activeThreadId, refreshSessions, selectSession, createSession]
  );

  const renameSession = useCallback(
    async (threadId: string, title: string) => {
      const trimmed = title.trim();
      if (!trimmed) return;
      try {
        await fetch(`/api/sessions/${threadId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: trimmed }),
        });
      } catch {
        toast.error("Không đổi tên được phiên.");
        return;
      }
      await refreshSessions();
    },
    [refreshSessions]
  );

  const togglePin = useCallback(
    async (threadId: string) => {
      const current = sessions.find((s) => s.thread_id === threadId);
      if (!current) return;
      try {
        await fetch(`/api/sessions/${threadId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pinned: !current.pinned }),
        });
      } catch {
        toast.error("Không ghim được phiên.");
        return;
      }
      await refreshSessions();
    },
    [sessions, refreshSessions]
  );

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void (async () => {
      const list = await refreshSessions();
      const cookieThreadId = getCookie(THREAD_COOKIE);
      const stillExists = cookieThreadId && list.some((s) => s.thread_id === cookieThreadId);
      if (stillExists) {
        setActiveThreadId(cookieThreadId);
      } else if (list.length > 0) {
        setCookie(THREAD_COOKIE, list[0].thread_id);
        setActiveThreadId(list[0].thread_id);
      } else {
        await createSession();
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <SessionsContext.Provider
      value={{
        sessions,
        activeThreadId,
        refreshSessions,
        createSession,
        selectSession,
        deleteSession,
        renameSession,
        togglePin,
      }}
    >
      {children}
    </SessionsContext.Provider>
  );
}

export function useSessions() {
  const ctx = useContext(SessionsContext);
  if (!ctx) throw new Error("useSessions must be used within SessionsProvider");
  return ctx;
}
