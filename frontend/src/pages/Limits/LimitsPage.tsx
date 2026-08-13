import { useState } from "react";

import {
  useAcknowledgeBreach,
  useCreateOrUpdateLimit,
  useLimits,
  useOpenBreaches,
  type BookLimitCreate,
} from "../../hooks/useLimits";
import { useSelection } from "../../hooks/useSelection";

const inputClass =
  "bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-slate-100 w-full";

export function LimitsPage() {
  const { bookId, commodity } = useSelection();
  const limits = useLimits(bookId);
  const breaches = useOpenBreaches(bookId);
  const createLimit = useCreateOrUpdateLimit();
  const acknowledge = useAcknowledgeBreach();

  const [limitType, setLimitType] = useState<BookLimitCreate["limit_type"]>("VOLUME");
  const [threshold, setThreshold] = useState("50000");
  const [confidenceLevel, setConfidenceLevel] = useState<95 | 99>(95);

  if (!bookId) {
    return <p className="text-sm text-slate-500">Select a book above to manage its limits.</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-sm uppercase tracking-wide text-slate-500 mb-2">
          Set a limit for this book ({commodity})
        </h2>
        <form
          className="flex flex-wrap items-end gap-3 bg-slate-900/50 p-4 rounded-lg border border-slate-800"
          onSubmit={(e) => {
            e.preventDefault();
            createLimit.mutate({
              book_id: bookId,
              commodity,
              limit_type: limitType,
              threshold: Number(threshold),
              confidence_level: confidenceLevel,
            });
          }}
        >
          <div>
            <label className="text-xs text-slate-400">Type</label>
            <select
              className={inputClass}
              value={limitType}
              onChange={(e) => setLimitType(e.target.value as BookLimitCreate["limit_type"])}
            >
              <option value="VOLUME">Volume (max net volume, blocks confirm)</option>
              <option value="VAR">VaR (alert only)</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-400">Threshold</label>
            <input className={inputClass} value={threshold} onChange={(e) => setThreshold(e.target.value)} />
          </div>
          {limitType === "VAR" && (
            <div>
              <label className="text-xs text-slate-400">Confidence level</label>
              <select
                className={inputClass}
                value={confidenceLevel}
                onChange={(e) => setConfidenceLevel(Number(e.target.value) as 95 | 99)}
              >
                <option value={95}>95%</option>
                <option value={99}>99%</option>
              </select>
            </div>
          )}
          <button
            type="submit"
            disabled={createLimit.isPending}
            className="bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-4 py-1.5 rounded-md disabled:opacity-50"
          >
            {createLimit.isPending ? "Saving…" : "Save limit"}
          </button>
        </form>
      </div>

      <div>
        <h2 className="text-sm uppercase tracking-wide text-slate-500 mb-2">Configured limits</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-800">
              <th className="py-1.5">Commodity</th>
              <th className="py-1.5">Type</th>
              <th className="py-1.5 text-right">Threshold</th>
              <th className="py-1.5 text-right">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {limits.data?.map((limit) => (
              <tr key={limit.id} className="border-b border-slate-900">
                <td className="py-1.5">{limit.commodity}</td>
                <td className="py-1.5">{limit.limit_type}</td>
                <td className="py-1.5 text-right">{limit.threshold.toLocaleString()}</td>
                <td className="py-1.5 text-right">
                  {limit.limit_type === "VAR" ? `${limit.confidence_level}%` : "—"}
                </td>
              </tr>
            ))}
            {limits.data?.length === 0 && (
              <tr>
                <td colSpan={4} className="py-3 text-slate-500">
                  No limits configured for this book yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div>
        <h2 className="text-sm uppercase tracking-wide text-slate-500 mb-2">Open breaches</h2>
        {breaches.data?.length === 0 && <p className="text-sm text-slate-500">No open breaches.</p>}
        <div className="space-y-2">
          {breaches.data?.map((breach) => (
            <div
              key={breach.id}
              className="bg-slate-900/50 border border-slate-800 rounded-lg p-3 flex items-center justify-between"
            >
              <div className="text-sm">
                <span className="font-medium">{breach.limit_type}</span>{" "}
                <span className="text-slate-400">
                  observed {breach.observed_value.toLocaleString()} vs. limit{" "}
                  {breach.threshold.toLocaleString()} on {breach.as_of_date}
                </span>
              </div>
              <button
                className="bg-slate-700 hover:bg-slate-600 text-xs px-3 py-1 rounded-md disabled:opacity-50"
                disabled={acknowledge.isPending}
                onClick={() => {
                  const note = window.prompt("Note (optional):") ?? undefined;
                  acknowledge.mutate({ breachId: breach.id, note });
                }}
              >
                Acknowledge
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
