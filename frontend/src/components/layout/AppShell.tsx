import { BarChart3, ClipboardList, FilePlus2, LayoutDashboard, ListChecks, LogOut, Menu, Settings, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Badge } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { ANALYST_ADMIN, STAFF, useAuth } from "@/lib/auth";
import type { Role } from "@/lib/schemas";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  roles?: Role[];
}

// Navigation filtering is a convenience only; the backend enforces every permission.
export const NAV: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, roles: ANALYST_ADMIN },
  { to: "/incidents", label: "Incident Explorer", icon: ClipboardList },
  { to: "/incidents/new", label: "Create Incident", icon: FilePlus2 },
  { to: "/queues", label: "Team Queues", icon: ListChecks, roles: STAFF },
  { to: "/analytics", label: "Analytics", icon: BarChart3, roles: ANALYST_ADMIN },
  { to: "/admin", label: "Admin Settings", icon: Settings, roles: ANALYST_ADMIN },
];

export function AppShell() {
  const { user, logout, hasRole } = useAuth();
  const [open, setOpen] = useState(false);
  const items = NAV.filter((n) => !n.roles || hasRole(...n.roles));

  const nav = (
    <nav aria-label="Main navigation" className="flex flex-col gap-1 p-3">
      {items.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/" || to === "/incidents"}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-slate-600 hover:bg-sky-50",
              isActive && "bg-gradient-to-r from-sky-100 to-violet-100 text-slate-900",
            )
          }
        >
          <Icon className="h-4 w-4" aria-hidden /> {label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[250px_1fr]">
      <aside className="hidden border-r border-slate-100 bg-white lg:block">
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-gradient-to-br from-sky-400 to-violet-400 text-white">
            <Sparkles className="h-4 w-4" aria-hidden />
          </span>
          <span className="font-semibold text-slate-900">IncidentIQ</span>
        </div>
        {nav}
      </aside>

      {open && (
        <div className="fixed inset-0 z-30 bg-slate-900/20 lg:hidden" onClick={() => setOpen(false)}>
          <aside className="h-full w-64 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-5">
              <span className="font-semibold">IncidentIQ</span>
              <Button variant="ghost" size="icon" aria-label="Close menu" onClick={() => setOpen(false)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
            {nav}
          </aside>
        </div>
      )}

      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-100 bg-white/90 px-4 py-3 backdrop-blur lg:px-8">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu" onClick={() => setOpen(true)}>
              <Menu className="h-5 w-5" />
            </Button>
            <Badge tone="violet">Academic demo · DA377</Badge>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <p className="text-sm font-medium text-slate-800">{user?.full_name}</p>
              <p className="text-xs text-slate-500">{user?.role.replace("_", " ")}</p>
            </div>
            <Button variant="outline" size="sm" onClick={logout}>
              <LogOut className="h-3.5 w-3.5" /> Sign out
            </Button>
          </div>
        </header>
        <main className="mx-auto max-w-7xl p-4 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
