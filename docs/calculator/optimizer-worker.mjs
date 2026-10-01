import loadHighs from "./solver/highs.mjs";
import { optimizeLoadout, preferRecommendation } from "./loadout-optimizer.mjs";

const runtime = loadHighs({locateFile: file => new URL(`./solver/${file}`, import.meta.url).href + new URL(import.meta.url).search});
self.onmessage = async ({data}) => {
  try {
    const highs = await runtime;
    const input = {...data, weapons: new Map(data.weapons)};
    const quick = optimizeLoadout(input, highs, {timeLimit: 2});
    if (quick.status === "optimal" || quick.status === "infeasible") { self.postMessage(quick); return; }
    if (quick.preset) self.postMessage({...quick, searching: true});
    const result = optimizeLoadout(input, highs, {timeLimit: data.timeLimit || 20});
    const betterQuick = preferRecommendation(quick, result, data.filters);
    self.postMessage(betterQuick ? quick : result);
  } catch (error) { self.postMessage({status: "error", message: error.message}); }
};
