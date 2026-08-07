import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../../auth/AuthContext";
import { useBooks } from "../../hooks/useReferenceData";
import type { Commodity } from "../../hooks/useSelection";
import { SelectionContext } from "../../hooks/useSelection";
import { RoleGate } from "../auth/RoleGate";

const navItems = [
  { to: "/", label: "Trade Blotter" },
  { to: "/curve", label: "Curve Viewer" },
  { to: "/risk", label: "Risk Dashboard" },
];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function AppShell() {
  const [bookId, setBookId] = useState<string | undefined>(undefined);
  const [commodity, setCommodity] = useState<Commodity>("HENRY_HUB");
  const [asOfDate, setAsOfDate] = useState<string>(todayIso());
  const { data: books } = useBooks();
  const { user, logout } = useAuth();

  return (
    <SelectionContext.Provider value={{ bookId, setBookId, commodity, setCommodity, asOfDate, setAsOfDate }}>
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <header className="border-b border-slate-800 px-6 py-4">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold tracking-tight">OpenETRM</h1>
            <div className="flex items-center gap-3 text-sm text-slate-400">
              <span>
                {user?.username} <span className="text-slate-600">({user?.role})</span>
              </span>
              <button onClick={logout} className="hover:text-slate-200">
                Sign out
              </button>
            </div>
          </div>
          <div className="mt-3 flex items-center justify-between gap-4 flex-wrap">
            <nav className="flex gap-4">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `text-sm px-3 py-1.5 rounded-md transition-colors ${
                      isActive ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
              <RoleGate roles={["RISK_MANAGER", "ADMIN"]}>
                <NavLink
                  to="/approvals"
                  className={({ isActive }) =>
                    `text-sm px-3 py-1.5 rounded-md transition-colors ${
                      isActive ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
                    }`
                  }
                >
                  Pending Approvals
                </NavLink>
              </RoleGate>
            </nav>
            <div className="flex items-center gap-3 text-sm">
              <label className="flex items-center gap-2 text-slate-400">
                Commodity
                <select
                  className="bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-slate-100"
                  value={commodity}
                  onChange={(e) => setCommodity(e.target.value as Commodity)}
                >
                  <option value="HENRY_HUB">Henry Hub</option>
                  <option value="WTI">WTI</option>
                </select>
              </label>
              <label className="flex items-center gap-2 text-slate-400">
                Book
                <select
                  className="bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-slate-100"
                  value={bookId ?? ""}
                  onChange={(e) => setBookId(e.target.value || undefined)}
                >
                  <option value="">Select a book…</option>
                  {books?.map((book) => (
                    <option key={book.id} value={book.id}>
                      {book.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-slate-400">
                As of
                <input
                  type="date"
                  className="bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-slate-100"
                  value={asOfDate}
                  onChange={(e) => setAsOfDate(e.target.value)}
                />
              </label>
            </div>
          </div>
        </header>
        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </SelectionContext.Provider>
  );
}
