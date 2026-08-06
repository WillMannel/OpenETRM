import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppShell } from "./AppShell";

function renderShell() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<div>blotter placeholder</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppShell", () => {
  it("renders the nav and the routed page content", () => {
    renderShell();

    expect(screen.getByText(/OpenETRM/)).toBeInTheDocument();
    expect(screen.getByText("Trade Blotter")).toBeInTheDocument();
    expect(screen.getByText("Curve Viewer")).toBeInTheDocument();
    expect(screen.getByText("Risk Dashboard")).toBeInTheDocument();
    expect(screen.getByText("blotter placeholder")).toBeInTheDocument();
  });
});
