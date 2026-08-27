import {StrictMode} from "react";
import {createRoot} from "react-dom/client";
import {App} from "./App";
import "leaflet/dist/leaflet.css";
import "./styles.css";
import "./twin-cockpit.css";
import "./workspace.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
