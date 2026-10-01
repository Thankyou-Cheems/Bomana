// Game-font substitutions, not text-encoding repairs. See the source research note.
import { vehiclePinyin } from "./vehicle-pinyin.mjs";
import { localizeName } from "./i18n.mjs";
const countries = { usa: "美国", ussr: "苏联", germany: "德国", britain: "英国",
  japan: "日本", china: "中国", italy: "意大利", france: "法国", sweden: "瑞典", israel: "以色列",
  thailand: "泰国", switzerland: "瑞士", netherlands: "荷兰", belgium: "比利时", greece: "希腊",
  australia: "澳大利亚", malaysia: "马来西亚", finland: "芬兰", hungary: "匈牙利",
  south_africa: "南非", indonesia: "印度尼西亚" };

const flags = { usa: "🇺🇸", germany: "🇩🇪", britain: "🇬🇧", japan: "🇯🇵", china: "🇨🇳",
  italy: "🇮🇹", france: "🇫🇷", sweden: "🇸🇪", israel: "🇮🇱", thailand: "🇹🇭",
  switzerland: "🇨🇭", netherlands: "🇳🇱", belgium: "🇧🇪", greece: "🇬🇷",
  australia: "🇦🇺", malaysia: "🇲🇾", finland: "🇫🇮", hungary: "🇭🇺",
  south_africa: "🇿🇦", indonesia: "🇮🇩" };

export function vehicleName(value, country) {
  // Source names remain untouched in the API. Only the leading game marker is
  // replaced, following getClearUnitName; country comes from unit metadata.
  return String(value ?? "").replace(/^[\uF059\u2415-\u2419\u241e-\u2420\u2580-\u2588◄◊◐◘◥◔◌◢◗◡⋠]/u,
    () => flags[country] ? `${flags[country]} ` : `〔${localizeName(countries[country] || "特殊型号")}〕`).trim();
}

export function readableVehicle(row) {
  return { ...row, get name() { return vehicleName(localizeName(row.name, row.name_en), row.country); }, get countryName() { return localizeName(countries[row.country] || ""); },
    searchTerms: vehicleSearchTerms(row),
    ...(row.long ? { get long() { return vehicleName(localizeName(row.long, row.name_en), row.country); } } : {}),
    ...(row.name_en ? { name_en: vehicleName(row.name_en, row.country) } : {}) };
}

function vehicleSearchTerms(row) {
  const names = [row.name, row.long, row.name_en].filter(Boolean);
  if (/^ef_2000/.test(row.id)) names.push("台风", "Eurofighter Typhoon", "EF 2000", "F 2000");
  const terms = new Set(names);
  for (const name of names) {
    for (const phrase of name.match(/[\u3400-\u9fff]+/gu) || []) {
      for (const spelling of vehiclePinyin[phrase] || []) terms.add(spelling);
    }
    for (const index of [0, 1]) terms.add(name.replace(/[\u3400-\u9fff]+/gu, phrase => vehiclePinyin[phrase]?.[index] || phrase));
  }
  return [...terms];
}
