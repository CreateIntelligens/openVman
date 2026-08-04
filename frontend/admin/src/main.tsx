import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";

async function updateMaterialIconAvailability() {
  const root = document.documentElement;
  if (!document.fonts) {
    root.classList.replace(
      "material-icons-loading",
      "material-icons-unavailable",
    );
    return;
  }

  try {
    await document.fonts.load('1rem "Material Symbols Outlined"');
    root.classList.replace(
      "material-icons-loading",
      document.fonts.check('1rem "Material Symbols Outlined"')
        ? "material-icons-ready"
        : "material-icons-unavailable",
    );
  } catch {
    root.classList.replace(
      "material-icons-loading",
      "material-icons-unavailable",
    );
  }
}

void updateMaterialIconAvailability();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
