import { AppSidebar } from "@/components/app-sidebar";
import { SessionsProvider } from "@/components/session-context";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionsProvider>
      <div className="flex h-screen w-full overflow-hidden">
        <AppSidebar />
        <div className="flex min-w-0 flex-1 flex-col">{children}</div>
      </div>
    </SessionsProvider>
  );
}
