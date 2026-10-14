import { t, numberLocale } from "./i18n.mjs";

// These opaque conclusions are compiled privately. The public calculator has
// no trajectory inputs, thresholds or solver and cannot authorize a live drop.
export function deliveryGroup(id, weapon, targetId = "") {
  const group = weapon?.releaseGroup?.[targetId.startsWith("airport_") ? "high" : "standard"];
  return group != null ? `release:${group}` : `weapon:${id}`;
}

export function loadoutSimplicity(items, weapons, targetId = "") {
  const ids = new Set(items.filter(([id, count]) => count > 0 && weapons.get(id)?.dmg > 0).map(([id]) => id));
  return {types: ids.size, profiles: new Set([...ids].map(id => deliveryGroup(id, weapons.get(id), targetId))).size};
}

export function releaseAssessment(items, weapons, targetId = "") {
  const ids = [...new Set(items.filter(([,count]) => count > 0).map(([id]) => id))];
  if (!ids.length) return "empty";
  if (ids.some(id => weapons.get(id)?.kind !== "bomb" || weapons.get(id)?.guidanceKind === "guided" || weapons.get(id)?.guidanceModes?.length)) return "individual";
  const mode = targetId.startsWith("airport_") ? "high" : "standard";
  if (ids.some(id => weapons.get(id)?.releaseGroup?.[mode] == null)) return "unknown";
  return new Set(ids.map(id => deliveryGroup(id, weapons.get(id), targetId))).size === 1 ? "compatible" : "separate";
}

export function releaseGap(items, data, targetId = "") {
  const ids = [...new Set(items.filter(([,count]) => count > 0).map(([id]) => id))];
  if (ids.length < 2 || !data) return null;
  const indices = ids.map(id => data.ids.findIndex(group => group.includes(id)));
  if (indices.some(index => index < 0)) return null;
  const offset = targetId.startsWith("airport_") ? 2 : 0, n = data.ids.length;
  let min = 0, max = 0;
  for (let i = 0; i < indices.length; i++) for (let j = i + 1; j < indices.length; j++) {
    const a = Math.min(indices[i], indices[j]), b = Math.max(indices[i], indices[j]);
    const row = a === b ? [0,0,0,0] : data.ranges[a * (2 * n - a - 1) / 2 + b - a - 1];
    if (!row || ![row[offset], row[offset + 1]].every(value => Number.isFinite(value) && value >= 0) || row[offset] > row[offset + 1]) return null;
    min = Math.max(min, row[offset]); max = Math.max(max, row[offset + 1]);
  }
  return {min, max};
}

export function releaseMessage(items, weapons, targetId = "", ranges) {
  const status = releaseAssessment(items, weapons, targetId);
  const messages = {
    empty: "",
    compatible: t("release.compatible", "可共用投弹点（规划参考）；实际投弹仍需按当前弹种确认 CCRP。"),
    separate: t("release.separate", "建议按弹种分别投弹、分别确认 CCRP；此挂载不建议共用一个投弹点。分批设置不会消除弹道差异。"),
    unknown: t("release.unknown", "投弹兼容性数据不足；建议按弹种分别确认 CCRP，勿假定可以一起投弹。"),
    individual: t("release.individual", "含制导弹药或其他武器：按各自制导／发射方式投放，不能把整套伤害视为一次 CCRP 齐投。"),
  };
  const gap = ["compatible", "separate"].includes(status) && releaseGap(items, ranges, targetId);
  const format = value => value.toLocaleString(numberLocale());
  const distance = gap ? " " + t("release.gap", "参考投弹点间距约 {{min}}–{{max}} 米（非实时落点误差）。", {min:format(gap.min), max:format(gap.max)}) : "";
  return messages[status] + distance + (status !== "empty" && targetId.startsWith("airport_")
    ? " " + t("release.airport", "机场模块按高空投弹兼容性评估；注意机场防空。") : "");
}
