import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import "@/styles/tokens.css";

const container = document.getElementById("root");
if (!container) throw new Error("Root container missing");
createRoot(container).render(<App />);
