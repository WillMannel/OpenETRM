import { useAuth } from "../../auth/AuthContext";
import {
  useConfirmTrade,
  useRequestAmendment,
  useRequestCancellation,
} from "../../hooks/useTrades";
import type { Trade } from "../../hooks/useTrades";

const CONFIRM_ROLES = ["RISK_MANAGER", "ADMIN"];
const REQUEST_ROLES = ["TRADER", "ADMIN"];

/** AG Grid cell renderer: shows the action(s) available for a trade's current status,
 * gated by the current user's role (cosmetically -- the backend enforces this
 * regardless). Amendment/cancellation reasons are collected via a plain prompt() --
 * a full modal form isn't worth the extra weight for what's a one-line free-text
 * field. */
export function TradeActionsCell({ data }: { data: Trade }) {
  const { user } = useAuth();
  const confirmTrade = useConfirmTrade();
  const requestAmendment = useRequestAmendment();
  const requestCancellation = useRequestCancellation();

  if (!user) return null;

  if (data.status === "NEW" && CONFIRM_ROLES.includes(user.role)) {
    return (
      <button
        className="text-xs text-emerald-400 hover:underline disabled:opacity-50"
        disabled={confirmTrade.isPending}
        onClick={() => confirmTrade.mutate(data.id)}
      >
        Confirm
      </button>
    );
  }

  if (data.status === "CONFIRMED" && REQUEST_ROLES.includes(user.role)) {
    return (
      <div className="flex gap-3">
        <button
          className="text-xs text-sky-400 hover:underline disabled:opacity-50"
          disabled={requestAmendment.isPending}
          onClick={() => {
            const newVolume = window.prompt("New volume (MMBtu):", String(data.volume));
            if (!newVolume) return;
            const reason = window.prompt("Reason for amendment:");
            if (!reason) return;
            requestAmendment.mutate({ tradeId: data.id, changes: { volume: Number(newVolume) }, reason });
          }}
        >
          Amend
        </button>
        <button
          className="text-xs text-red-400 hover:underline disabled:opacity-50"
          disabled={requestCancellation.isPending}
          onClick={() => {
            const reason = window.prompt("Reason for cancellation:");
            if (!reason) return;
            requestCancellation.mutate({ tradeId: data.id, reason });
          }}
        >
          Cancel
        </button>
      </div>
    );
  }

  if (data.status === "PENDING_AMENDMENT" || data.status === "PENDING_CANCELLATION") {
    return <span className="text-xs text-amber-400">Pending approval</span>;
  }

  return null;
}
