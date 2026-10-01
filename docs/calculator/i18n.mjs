import i18next from "./vendor/i18next.mjs";

export const languages = ["zh-CN", "zh-Hant", "en"];
let locale = "zh-CN", catalogNames = {};
await i18next.init({lng: locale, fallbackLng: "zh-CN", keySeparator: false, nsSeparator: false,
  resources: {}, interpolation: {escapeValue: false}});
export const currentLocale = () => locale;
export const numberLocale = () => locale === "zh-Hant" ? "zh-HK" : locale;
export const t = (key, fallback = key, values = {}) => i18next.t(key, {defaultValue: fallback, ...values});
export const localizeName = (value, english) => locale === "en" && english ? english : catalogNames[value] || value;

export async function changeLanguage(next) {
  if (!languages.includes(next)) next = "zh-CN";
  const revision = new URL(import.meta.url).search;
  const read = async file => {
    const response = await fetch(new URL(`./locales/${file}.json${revision}`, import.meta.url));
    if (!response.ok) throw new Error("locale_unavailable");
    return response.json();
  };
  const [strings, names] = await Promise.all([read(next), next === "zh-CN" ? {} : read(`catalog-${next}`)]);
  i18next.addResourceBundle(next, "translation", strings, true, true);
  catalogNames = names; locale = next;
  await i18next.changeLanguage(next);
  try { localStorage.setItem("bomana:calculator:language", next); } catch { /* Session-only choice. */ }
  document.documentElement.lang = next;
  translatePage();
  document.dispatchEvent(new Event("calculator:language"));
}

export function translatePage() {
  for (const element of document.querySelectorAll("[data-i18n]")) element.textContent = t(element.dataset.i18n, element.textContent);
  for (const attribute of ["aria-label", "placeholder", "title", "alt", "content"]) {
    for (const element of document.querySelectorAll(`[data-i18n-${attribute}]`)) element.setAttribute(attribute, t(element.getAttribute(`data-i18n-${attribute}`), element.getAttribute(attribute)));
  }
}

export async function initializeLanguage() {
  let choice;
  try { choice = localStorage.getItem("bomana:calculator:language"); } catch { /* Use the default language. */ }
  if (!languages.includes(choice)) choice = "zh-CN";
  const picker = document.querySelector("#calculatorLanguage");
  try { await changeLanguage(choice); } catch { locale = "zh-CN"; }
  const buttons = [...picker.querySelectorAll("[data-calculator-language]")];
  const reflect = () => buttons.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.calculatorLanguage === locale)));
  reflect();
  picker.addEventListener("click", async event => {
    const selected = event.target.closest("[data-calculator-language]");
    if (!selected || selected.disabled || selected.dataset.calculatorLanguage === locale) return;
    buttons.forEach(button => { button.disabled = true; });
    picker.setAttribute("aria-busy", "true");
    try { await changeLanguage(selected.dataset.calculatorLanguage); } catch { /* Keep the current language if loading fails. */ }
    finally {
      buttons.forEach(button => { button.disabled = false; });
      picker.removeAttribute("aria-busy"); reflect(); selected.focus();
    }
  });
}
