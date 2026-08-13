import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../auth/AuthContext", async () => {
  const actual = await vi.importActual<typeof import("../../auth/AuthContext")>("../../auth/AuthContext");
  return { ...actual, useAuth: vi.fn() };
});

import { useAuth } from "../../auth/AuthContext";
import { RoleGate } from "./RoleGate";

const mockUseAuth = vi.mocked(useAuth);

describe("RoleGate", () => {
  it("renders children when the user's role is allowed", () => {
    mockUseAuth.mockReturnValue({
      user: { id: "1", username: "risk-a", email: "a@example.com", role: "RISK_MANAGER", is_active: true, created_at: "" },
      isLoading: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <RoleGate roles={["RISK_MANAGER", "ADMIN"]}>
        <span>secret button</span>
      </RoleGate>,
    );

    expect(screen.getByText("secret button")).toBeInTheDocument();
  });

  it("hides children when the user's role is not allowed", () => {
    mockUseAuth.mockReturnValue({
      user: { id: "1", username: "viewer", email: "v@example.com", role: "VIEWER", is_active: true, created_at: "" },
      isLoading: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <RoleGate roles={["RISK_MANAGER", "ADMIN"]}>
        <span>secret button</span>
      </RoleGate>,
    );

    expect(screen.queryByText("secret button")).not.toBeInTheDocument();
  });

  it("hides children when there is no user", () => {
    mockUseAuth.mockReturnValue({
      user: null,
      isLoading: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <RoleGate roles={["VIEWER"]}>
        <span>secret button</span>
      </RoleGate>,
    );

    expect(screen.queryByText("secret button")).not.toBeInTheDocument();
  });
});
