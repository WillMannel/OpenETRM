import {
  useApproveChangeRequest,
  usePendingChangeRequests,
  useRejectChangeRequest,
} from "../../hooks/useChangeRequests";

export function PendingApprovalsPage() {
  const { data: requests, isLoading } = usePendingChangeRequests();
  const approve = useApproveChangeRequest();
  const reject = useRejectChangeRequest();

  return (
    <div className="space-y-4">
      <h2 className="text-sm uppercase tracking-wide text-slate-500">Pending change requests</h2>

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {!isLoading && requests?.length === 0 && (
        <p className="text-sm text-slate-500">Nothing pending review.</p>
      )}

      <div className="space-y-3">
        {requests?.map((req) => (
          <div key={req.id} className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-medium">
                  {req.change_type} — trade {req.trade_id.slice(0, 8)}…
                </div>
                <div className="text-xs text-slate-500 mt-1">{req.reason}</div>
                {req.proposed_changes && (
                  <pre className="text-xs text-slate-400 mt-2 bg-slate-950 rounded p-2 overflow-x-auto">
                    {JSON.stringify(req.proposed_changes, null, 2)}
                  </pre>
                )}
              </div>
              <div className="flex gap-2 shrink-0">
                <button
                  className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium px-3 py-1.5 rounded-md disabled:opacity-50"
                  disabled={approve.isPending}
                  onClick={() => approve.mutate({ id: req.id })}
                >
                  Approve
                </button>
                <button
                  className="bg-red-700 hover:bg-red-600 text-white text-xs font-medium px-3 py-1.5 rounded-md disabled:opacity-50"
                  disabled={reject.isPending}
                  onClick={() => {
                    const note = window.prompt("Reason for rejecting (optional):") ?? undefined;
                    reject.mutate({ id: req.id, note });
                  }}
                >
                  Reject
                </button>
              </div>
            </div>
            {(approve.isError || reject.isError) && (
              <p className="text-xs text-red-400 mt-2">
                Action failed — you may be the same user who requested this change (four-eyes).
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
