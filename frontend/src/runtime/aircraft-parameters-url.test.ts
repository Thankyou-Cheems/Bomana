import { describe, expect, it } from "vitest";
import { aircraftParametersURL } from "./aircraft-parameters-url";

const name = "aircraft-parameters-585283f9ad479775.json";
describe("aircraft resource delivery", () => {
  it.each(["Standard", "Enhanced"])("keeps %s phone resources inside the paired Bridge route", edition => {
    const page = new URL(`http://192.168.1.20:43123/mobile/${edition}/`);
    expect(aircraftParametersURL(name, new URL("assets/main-12345678.js", page).href, false, page).href)
      .toBe(new URL(`assets/${name}`, page).href);
  });
  it("shares browser files while keeping packaged and dev files local", () => {
    const page = new URL("https://bomana.ruikang.wang/app/Enhanced/");
    expect(aircraftParametersURL(name, new URL("assets/main-12345678.js", page).href, false, page).pathname)
      .toBe(`/app/shared/${name}`);
    expect(aircraftParametersURL(name, "http://127.0.0.1:5173/src/generated/public-offline-assets.ts", true, page).pathname)
      .toBe("/src/generated/aircraft-parameters.json");
    expect(aircraftParametersURL(name, "https://app.localhost/assets/main-12345678.js", false, new URL("https://app.localhost/")).pathname)
      .toBe(`/assets/${name}`);
  });
});
