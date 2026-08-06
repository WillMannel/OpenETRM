import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useBooks } from "../../hooks/useReferenceData";
import { SelectionContext } from "../../hooks/useSelection";

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
  const [asOfDate, setAsOfDate] = useState<string>(todayIso());
  const { data: books } = useBooks();

  return (
    <SelectionContext.Provider value={{ bookId, setBookId, asOfDate, setAsOfDate }}>
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <header className="border-b border-slate-800 px-6 py-4">
          <h1 className="text-lg font-semibold tracking-tight">
            OpenETRM <span className="text-slate-500 font-normal">/ Henry Hub pilot book</span>
          </h1>
          <div className="mt-3 flex items-center justify-between gap-4">
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
            </nav>
            <div className="flex items-center gap-3 text-sm">
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
