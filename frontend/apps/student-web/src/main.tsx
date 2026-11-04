import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./app/App";
import "@edu/ui/styles.css";
import "./styles.css";

document.documentElement.classList.add("student-portal");

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
