function normalizedWords(value) {
  return String(value ?? "")
    .normalize("NFKD")
    .replace(/\p{M}+/gu, "")
    .toLowerCase()
    .replace(/[\p{P}\p{S}\s_]+/gu, " ")
    .trim();
}

function subsequenceScore(needle, haystack) {
  let cursor = -1;
  let gaps = 0;
  for (const character of needle) {
    const next = haystack.indexOf(character, cursor + 1);
    if (next < 0) return Number.POSITIVE_INFINITY;
    if (cursor >= 0) gaps += next - cursor - 1;
    cursor = next;
  }
  return 40 + gaps * 2 + Math.max(0, haystack.length - needle.length) * 0.05;
}

function tokenScore(token, words) {
  const joined = words.replace(/\s+/g, "");
  // Both sides are already normalized; a token/word contains no whitespace.
  const query = token;
  if (!query || !joined) return Number.POSITIVE_INFINITY;
  if (words === token || joined === query) return 0;
  const wordList = words.split(" ");
  if (wordList.includes(token)) return 3;
  if (joined.startsWith(query)) return 8 + (joined.length - query.length) * 0.01;
  const containedAt = joined.indexOf(query);
  if (containedAt >= 0) return 16 + containedAt + (joined.length - query.length) * 0.01;
  return subsequenceScore(query, joined);
}

function scoreTokens(tokens, values) {
  if (!tokens.length) return 0;
  const candidates = values.map(normalizedWords).filter(Boolean);
  let total = 0;
  for (const token of tokens) {
    let best = Number.POSITIVE_INFINITY;
    for (const candidate of candidates) best = Math.min(best, tokenScore(token, candidate));
    if (!Number.isFinite(best)) return Number.POSITIVE_INFINITY;
    total += best;
  }
  return total;
}

export function fuzzySearchScore(query, values) {
  return scoreTokens(normalizedWords(query).split(" ").filter(Boolean), values);
}

export function rankFuzzyMatches(items, query, valuesForItem, limit = Number.POSITIVE_INFINITY) {
  const normalizedQuery = normalizedWords(query);
  if (!normalizedQuery) return items.slice(0, limit);
  const tokens = normalizedQuery.split(" ");
  return items
    .map((item, index) => ({ item, index, score: scoreTokens(tokens, valuesForItem(item)) }))
    .filter((entry) => Number.isFinite(entry.score))
    .sort((left, right) => left.score - right.score || left.index - right.index)
    .slice(0, limit)
    .map((entry) => entry.item);
}
