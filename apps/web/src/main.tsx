import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { AuthProvider } from "./auth/AuthProvider";
import "./styles/globals.css";
import { AppProviders } from "./ui/AppProviders";
import { installUiCssVariables } from "./ui/tokens";

installUiCssVariables();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppProviders>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </AppProviders>
  </React.StrictMode>,
);
