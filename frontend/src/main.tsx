import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { FournisseurAuth } from "./auth";
import "./styles.css";

createRoot(document.getElementById("racine")!).render(
  <StrictMode>
    <BrowserRouter>
      <FournisseurAuth>
        <App />
      </FournisseurAuth>
    </BrowserRouter>
  </StrictMode>,
);
