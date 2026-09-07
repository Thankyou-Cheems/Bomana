import "./public-styles.css";
import { applySavedTheme } from "./runtime/theme-preference";
import { authorizeMobileStandard } from "./runtime/mobile-bootstrap";
import { reportDailyActive } from "./runtime/anonymous-daily-active";

applySavedTheme();
if (__BOMANA_EDITION__ === "Enhanced") throw new Error("Enhanced requires its private entry point");
if (__BOMANA_EDITION__ === "Standard" && location.pathname.startsWith("/mobile/Standard/")) {
  await authorizeMobileStandard(() => import("./public-main"));
} else {
  await import("./public-main");
  void reportDailyActive(__BOMANA_EDITION__);
}
