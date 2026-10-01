const screenshotSlots = [...document.querySelectorAll(".shot[data-shot]")];

function loadScreenshot(slot) {
  if (slot.dataset.loaded === "pending" || slot.dataset.loaded === "true") return;
  const path = slot.getAttribute("data-shot");
  const image = slot.querySelector(".shot-img");
  if (!path || !image) return;
  slot.dataset.loaded = "pending";
  const probe = new Image();
  probe.onload = () => {
    image.src = path;
    image.width = probe.naturalWidth;
    image.height = probe.naturalHeight;
    image.hidden = false;
    slot.classList.add("is-loaded");
    slot.dataset.loaded = "true";
  };
  probe.onerror = () => { slot.dataset.loaded = "error"; };
  probe.src = path;
}

if ("IntersectionObserver" in window) {
  const shotObserver = new IntersectionObserver((entries, observer) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      loadScreenshot(entry.target);
      observer.unobserve(entry.target);
    }
  }, { rootMargin: "600px 0px" });
  for (const slot of screenshotSlots) shotObserver.observe(slot);
} else {
  for (const slot of screenshotSlots) loadScreenshot(slot);
}
