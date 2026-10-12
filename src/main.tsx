import { createRoot } from "react-dom/client";
import App from "./app/App.tsx";
import "./styles/index.css";
import "@fontsource-variable/figtree";
import "@vibe/core/tokens";
import "./styles/server.css";

createRoot(document.getElementById("root")!).render(<App />);
