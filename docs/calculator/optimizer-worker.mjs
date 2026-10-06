import loadHighs from "./solver/highs.mjs";
import { createOptimizerSession, preferRecommendation } from "./loadout-optimizer.mjs";

const runtime = loadHighs({locateFile: file => new URL(`./solver/${file}`, import.meta.url).href + new URL(import.meta.url).search});
let session, contextKey;
self.onmessage = async ({data}) => {
  const send = result => self.postMessage({...result, requestId: data.requestId});
  try {
    const highs = await runtime;
    if (data.context) {
      session = createOptimizerSession({...data.context, weapons: new Map(data.context.weapons)}, highs);
      contextKey = data.contextKey;
    }
    if (!session || contextKey !== data.contextKey) throw new Error("missing_optimizer_context");
    const quick = session(data, {timeLimit: 2});
    if (["optimal", "infeasible", "invalid"].includes(quick.status)) { send(quick); return; }
    if (quick.preset) send({...quick, searching: true});
    const result = session(data, {timeLimit: data.timeLimit || 20});
    const betterQuick = preferRecommendation(quick, result, data.filters);
    send(betterQuick ? quick : result);
  } catch (error) { send({status: "error", message: error.message}); }
};
