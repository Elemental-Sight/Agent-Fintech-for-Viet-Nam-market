"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  MessageSquare,
  Gauge,
  Filter,
  TrendingUp,
  ChevronsLeft,
  ChevronsRight,
  Plus,
  Pin,
  PinOff,
  Pencil,
  Trash2,
  MoreHorizontal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSessions } from "@/components/session-context";
import type { SessionOut } from "@/lib/types";

const NAV_ITEMS = [
  { href: "/chat", label: "Trò chuyện", icon: MessageSquare },
  { href: "/observability", label: "Quan sát hệ thống", icon: Gauge },
  { href: "/screener", label: "Bộ lọc cổ phiếu", icon: Filter },
];

// 3-row sidebar: (1) logo + collapse/expand toggle, (2) nav menu, (3) session
// list with per-session pin/rename/delete -- visible on every page (not just
// Chat) since navigating to it re-selects that thread via SessionsProvider.
export function AppSidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const { sessions, activeThreadId, createSession, selectSession, deleteSession, renameSession, togglePin } =
    useSessions();
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  function startRename(threadId: string, currentTitle: string) {
    setRenamingId(threadId);
    setRenameValue(currentTitle);
  }

  function commitRename() {
    if (renamingId && renameValue.trim()) {
      void renameSession(renamingId, renameValue);
    }
    setRenamingId(null);
  }

  const pinned = sessions.filter((s) => s.pinned);
  const others = sessions.filter((s) => !s.pinned);

  return (
    <nav
      className={cn(
        "flex h-full flex-col border-r bg-muted/30 transition-[width] duration-150",
        collapsed ? "w-16" : "w-72"
      )}
    >
      <div className={cn("flex items-center p-3", collapsed ? "flex-col gap-2" : "justify-between")}>
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <TrendingUp className="h-5 w-5" />
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? "Mở rộng" : "Thu gọn"}
        >
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
        </Button>
      </div>

      <Separator />

      <div className="flex flex-col gap-1 p-2">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          const link = (
            <Link
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                collapsed && "justify-center px-0",
                active
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <Icon className="h-5 w-5 shrink-0" />
              {!collapsed && <span className="truncate">{label}</span>}
            </Link>
          );
          return collapsed ? (
            <Tooltip key={href}>
              <TooltipTrigger asChild>{link}</TooltipTrigger>
              <TooltipContent side="right">{label}</TooltipContent>
            </Tooltip>
          ) : (
            <div key={href}>{link}</div>
          );
        })}
      </div>

      {!collapsed && (
        <>
          <Separator />
          <div className="p-3 pb-2">
            <Button onClick={() => void createSession()} className="w-full justify-start gap-2" variant="secondary">
              <Plus className="h-4 w-4" />
              Phiên mới
            </Button>
          </div>
          <ScrollArea className="min-h-0 flex-1">
            <div className="flex flex-col gap-2 p-2 pt-0">
              <SessionGroup
                label={pinned.length > 0 ? "Đã ghim" : undefined}
                items={pinned}
                activeThreadId={activeThreadId}
                renamingId={renamingId}
                renameValue={renameValue}
                onRenameValueChange={setRenameValue}
                onSelect={selectSession}
                onStartRename={startRename}
                onCommitRename={commitRename}
                onCancelRename={() => setRenamingId(null)}
                onDelete={deleteSession}
                onTogglePin={togglePin}
              />
              <SessionGroup
                label={pinned.length > 0 ? "Khác" : undefined}
                items={others}
                activeThreadId={activeThreadId}
                renamingId={renamingId}
                renameValue={renameValue}
                onRenameValueChange={setRenameValue}
                onSelect={selectSession}
                onStartRename={startRename}
                onCommitRename={commitRename}
                onCancelRename={() => setRenamingId(null)}
                onDelete={deleteSession}
                onTogglePin={togglePin}
              />
              {sessions.length === 0 && <p className="p-2 text-xs text-muted-foreground">Chưa có phiên nào.</p>}
            </div>
          </ScrollArea>
        </>
      )}
    </nav>
  );
}

function SessionGroup({
  label,
  items,
  activeThreadId,
  renamingId,
  renameValue,
  onRenameValueChange,
  onSelect,
  onStartRename,
  onCommitRename,
  onCancelRename,
  onDelete,
  onTogglePin,
}: {
  label?: string;
  items: SessionOut[];
  activeThreadId: string | null;
  renamingId: string | null;
  renameValue: string;
  onRenameValueChange: (v: string) => void;
  onSelect: (id: string) => void;
  onStartRename: (id: string, title: string) => void;
  onCommitRename: () => void;
  onCancelRename: () => void;
  onDelete: (id: string) => void;
  onTogglePin: (id: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-col gap-0.5">
      {label && <p className="px-2 pb-1 pt-2 text-xs font-medium text-muted-foreground">{label}</p>}
      {items.map((session) => {
        const active = session.thread_id === activeThreadId;
        const isRenaming = renamingId === session.thread_id;
        return (
          <div
            key={session.thread_id}
            className={cn(
              "group flex items-center gap-1.5 rounded-md px-2 py-2 text-sm cursor-pointer",
              active ? "bg-primary/10 text-primary" : "hover:bg-muted"
            )}
            onClick={() => !isRenaming && onSelect(session.thread_id)}
          >
            {isRenaming ? (
              <input
                autoFocus
                value={renameValue}
                onChange={(e) => onRenameValueChange(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onCommitRename();
                  if (e.key === "Escape") onCancelRename();
                }}
                onBlur={onCommitRename}
                className="min-w-0 flex-1 rounded border bg-background px-1.5 py-0.5 text-sm outline-none"
              />
            ) : (
              <span className="flex-1 truncate">{session.title || "Phiên mới"}</span>
            )}
            {!isRenaming && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    onClick={(e) => e.stopPropagation()}
                    className="shrink-0 rounded p-1 opacity-0 hover:bg-muted-foreground/10 focus:opacity-100 group-hover:opacity-100"
                    title="Tùy chọn"
                  >
                    <MoreHorizontal className="h-3.5 w-3.5" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                  <DropdownMenuItem onSelect={() => onTogglePin(session.thread_id)}>
                    {session.pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
                    {session.pinned ? "Bỏ ghim" : "Ghim"}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => onStartRename(session.thread_id, session.title)}>
                    <Pencil className="h-4 w-4" />
                    Đổi tên
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" onSelect={() => onDelete(session.thread_id)}>
                    <Trash2 className="h-4 w-4" />
                    Xóa
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        );
      })}
    </div>
  );
}
