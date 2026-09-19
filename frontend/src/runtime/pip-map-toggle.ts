/** Window-owned action, mounted last in the shared instrument action row. */
export function createPipMapToggle(document: Document, onClick: () => void): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.id = "pip-map-toggle";
  button.className = "pip-map-toggle";
  button.textContent = "小地图";
  button.addEventListener("click", onClick);
  return button;
}

export function updatePipMapToggle(button: HTMLButtonElement, visible: boolean): void {
  button.setAttribute("aria-pressed", String(visible));
  button.setAttribute("aria-expanded", String(visible));
  button.dataset.actionIcon = visible ? "▾" : "▸";
  button.title = visible ? "点击收起小地图" : "点击展开小地图";
  button.setAttribute("aria-label", button.title);
}
