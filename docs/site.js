const screenshotSlots = document.querySelectorAll(".shot[data-shot]");

for (const slot of screenshotSlots) {
  const path = slot.getAttribute("data-shot");
  const image = slot.querySelector(".shot-img");
  if (!path || !image) continue;
  const probe = new Image();
  probe.onload = () => {
    image.src = path;
    image.width = probe.naturalWidth;
    image.height = probe.naturalHeight;
    image.hidden = false;
    slot.classList.add("is-loaded");
  };
  probe.src = path;
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
