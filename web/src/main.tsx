import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("index.html is missing its #root element");

createRoot(root).render(
  <StrictMode>
    {/* The router's basename is Vite's base, so `/akn/...` identifiers keep working when the
        whole site is served under a repository path. */}
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
