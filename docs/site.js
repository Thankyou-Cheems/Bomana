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

const sectionLinks = [...document.querySelectorAll('.nav-links a[href^="#"]')];
const sections = sectionLinks
  .map((link) => document.querySelector(link.getAttribute("href")))
  .filter(Boolean);

if (sections.length && "IntersectionObserver" in window) {
  const observer = new IntersectionObserver((entries) => {
    const current = entries
      .filter((entry) => entry.isIntersecting)
      .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
    if (!current) return;
    for (const link of sectionLinks) {
      link.toggleAttribute("aria-current", link.getAttribute("href") === `#${current.target.id}`);
    }
  }, { rootMargin: "-20% 0px -70%", threshold: [0.05, 0.25, 0.6] });
  for (const section of sections) observer.observe(section);
}
