import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import App from "./App";
import { WorkflowStoreProvider } from "./app/workflowStore";


describe("App", () => {
  it("renders the workflow shell", () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <WorkflowStoreProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </WorkflowStoreProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText("Visual Network and Change Management")).toBeInTheDocument();
    expect(screen.getByText("GNS3 Connection")).toBeInTheDocument();
    expect(screen.getByText("Topology Builder")).toBeInTheDocument();
  });
});
