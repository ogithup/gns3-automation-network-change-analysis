import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { WorkflowStoreProvider } from "./app/workflowStore";
import "./styles.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <WorkflowStoreProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </WorkflowStoreProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
