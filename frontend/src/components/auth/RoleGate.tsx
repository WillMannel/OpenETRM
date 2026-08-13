import type { ReactNode } from "react";

import { useAuth } from "../../auth/AuthContext";
import type { UserRole } from "../../auth/AuthContext";

/** Hides `children` unless the current user's role is in `roles`. Purely cosmetic --
 * the backend enforces every one of these checks independently via require_role(...),
 * so this only controls whether a button/page shows up, never whether an action
 * actually succeeds. */
export function RoleGate({ roles, children }: { roles: UserRole[]; children: ReactNode }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role)) return null;
  return <>{children}</>;
}
