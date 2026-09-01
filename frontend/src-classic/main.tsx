import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import AuthGuard from "./components/AuthGuard";
import "./index.css";

const basename = window.location.pathname.startsWith("/classic") ? "/classic" : undefined;

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basename}>
        <AuthGuard>
          <App />
        </AuthGuard>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
