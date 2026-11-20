import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { Showcase } from "./Showcase";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root element");

createRoot(root).render(
  <StrictMode>
    <Showcase />
  </StrictMode>,
);
