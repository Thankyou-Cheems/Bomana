// Inspect rendered CSS pixels, not source spelling or projection internals.
export function measureLandingGuidance(canvas) {
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  const data = ctx.getImageData(0, 0, width, height).data;
  const display = canvas.getBoundingClientRect(), ratio = width / display.width;
  // Measure displayed CSS pixels, outside the pavement and its entrance.
  // The entrance is cyan too: counting all cyan pixels accepted a missing route.
  const side = Math.max(54, Math.min(125, display.width * .18));
  const pad = Math.max(8, Math.min(20, display.width * .025));
  const white = [], cyan = [];
  // The caption is muted, not cyan/white. Inspect the whole drawing area:
  // a fixed 28 px exclusion would discard much of a short strip's actual route.
  for (let y = Math.ceil(4 * ratio); y < height - 8 * ratio; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      const [r, g, b] = [data[i], data[i + 1], data[i + 2]];
      const light = data[i + 3] > 180 && r > 170 && g > 175 && b > 175 && Math.max(r, g, b) - Math.min(r, g, b) < 35;
      if (x < (side + pad + 2) * ratio || x > width - (side + pad + 2) * ratio) continue;
      if (light) white.push([x / ratio, y / ratio]);
      if (data[i + 3] > 128 && g > 150 && b > 140 && g - r > 30) cyan.push([x / ratio, y / ratio]);
    }
  }
  const bounds = points => points.reduce((box, [x, y]) => ({
    left: Math.min(box.left, x), right: Math.max(box.right, x),
    top: Math.min(box.top, y), bottom: Math.max(box.bottom, y),
  }), { left: Infinity, right: -Infinity, top: Infinity, bottom: -Infinity });
  const pavement = bounds(white);
  const route = cyan.filter(([x, y]) => x < pavement.left - 6 || x > pavement.right + 6
    || y < pavement.top - 6 || y > pavement.bottom + 6);
  const box = bounds(route);
  return { pavement, cyan: bounds(cyan), light: white.length / ratio ** 2, routeArea: route.length / ratio ** 2,
    routeSpan: route.length ? Math.max(box.right - box.left, box.bottom - box.top) : 0,
    width, height, quality: canvas.dataset.landingQuality, displayWidth: display.width, displayHeight: display.height };
}
