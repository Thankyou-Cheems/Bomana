import { setFlightDisplayMode, type FlightDisplayMode } from "./flight-display-mode";
import "../flight-mode-switch.css";

/** Both layouts expose the same one-click choice; each owns its active segment. */
export function flightModeSwitch(doc: Document, active: FlightDisplayMode): HTMLElement {
  const root = doc.createElement("div");
  root.className = "flight-mode-switch";
  root.setAttribute("role", "group");
  root.setAttribute("aria-label", "飞行显示模式");
  for (const [mode, label] of [["simulator", "全真"], ["air-realistic", "空历"]] as const) {
    const button = doc.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.dataset.mode = mode;
    button.setAttribute("aria-pressed", String(mode === active));
    button.title = mode === active ? `当前：${label}` : `切换到${label}`;
    button.addEventListener("click", () => {
      setFlightDisplayMode(mode);
      // The clicked layout is now hidden; keep keyboard focus in the visible choice.
      const selected = [...doc.querySelectorAll<HTMLButtonElement>(`.flight-mode-switch [data-mode="${mode}"][aria-pressed="true"]`)]
        .find(candidate => candidate.getClientRects().length > 0);
      selected?.focus({ preventScroll: true });
    });
    root.append(button);
  }
  return root;
}
