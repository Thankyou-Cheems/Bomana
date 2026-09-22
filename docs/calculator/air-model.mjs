// Short-horizon, constant-speed encounter model. Radar observations are an
// explicit input, never inferred from a 90-degree aspect or from chaff counts.
const G = 9.81, RAD = Math.PI / 180;
const add = (a, b) => a.map((v, i) => v + b[i]);
const sub = (a, b) => a.map((v, i) => v - b[i]);
const scale = (a, s) => a.map(v => v * s);
const dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0);
const length = a => Math.hypot(...a);
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = a => length(a) > 1e-10 ? scale(a, 1 / length(a)) : [0, 0, 0];
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export function curveValue(points, x) {
  if (x <= points[0][0]) return points[0][1];
  for (let i = 1; i < points.length; i++) {
    if (x <= points[i][0]) {
      const [x0, y0] = points[i - 1], [x1, y1] = points[i];
      return y0 + (y1 - y0) * (x - x0) / (x1 - x0);
    }
  }
  return points.at(-1)[1];
}

// Exact constant-velocity lead, used only to initialize a stated scenario.
export function interceptVelocity(relativePosition, targetVelocity, missileSpeed) {
  const a = dot(targetVelocity, targetVelocity) - missileSpeed ** 2;
  const b = 2 * dot(relativePosition, targetVelocity), c = dot(relativePosition, relativePosition);
  const discriminant = b * b - 4 * a * c;
  const roots = Math.abs(a) < 1e-9 ? [-c / b] : discriminant >= 0
    ? [(-b + Math.sqrt(discriminant)) / (2 * a), (-b - Math.sqrt(discriminant)) / (2 * a)] : [];
  const timeS = Math.min(...roots.filter(t => Number.isFinite(t) && t > 0));
  return Number.isFinite(timeS)
    ? { velocity: scale(add(relativePosition, scale(targetVelocity, timeS)), 1 / timeS), timeS }
    : null;
}

export function encounterGeometry(relativePosition, targetVelocity, missileVelocity) {
  const rangeM = length(relativePosition), los = unit(relativePosition);
  const relativeVelocity = sub(targetVelocity, missileVelocity);
  const closingMps = -dot(relativeVelocity, los);
  const omega = scale(cross(relativePosition, relativeVelocity), 1 / Math.max(rangeM ** 2, 1e-8));
  return { rangeM, los, omega, closingMps, losRateDegS: length(omega) / RAD,
    targetRadialMps: dot(targetVelocity, los),
    timeToGoS: closingMps > 0 ? rangeM / closingMps : null };
}

export function guidanceCommand(weapon, geometry, missileVelocity, elapsedS) {
  const modulation = curveValue(weapon.timeGain, elapsedS) *
    curveValue(weapon.interceptGain, geometry.timeToGoS ?? 1e6);
  const gain = modulation < .001 ? 0 : weapon.navigationConstant * modulation;
  // Kinematic omega-to-acceleration channel; complete loft/PID/airframe absent.
  // Native uses V x (v_rel x r / r²); our opposite omega convention is equivalent.
  // Curve inputs (age and range/closing) are model assumptions, not closed native clocks.
  const request = scale(cross(geometry.omega, missileVelocity), gain);
  const requestedG = length(request) / G;
  const limited = requestedG > weapon.commandLimitG;
  return { acceleration: limited ? scale(request, weapon.commandLimitG / requestedG) : request,
    requestedG, limited, gain };
}

function rotateToward(velocity, desired, maxAngle, fallbackAxis = [0, 0, 1]) {
  const speed = length(velocity), from = unit(velocity), to = unit(desired);
  if (length(to) < .5) return velocity;
  const angle = Math.acos(clamp(dot(from, to), -1, 1));
  if (angle < 1e-9) return velocity;
  let axis = unit(cross(from, to));
  if (length(axis) < .5) axis = unit(sub(fallbackAxis, scale(from, dot(fallbackAxis, from))));
  const turn = Math.min(angle, maxAngle), tangent = cross(axis, from);
  return scale(add(scale(from, Math.cos(turn)), scale(tangent, Math.sin(turn))), speed);
}

function targetStep(velocity, relative, initialVelocity, mode, acceleration, dt) {
  let desired;
  if (mode === "beam") {
    const n = unit(relative);
    desired = sub(velocity, scale(n, dot(velocity, n)));
    if (length(desired) < 1e-6) desired = cross([0, 0, 1], n);
  } else if (mode === "cold") desired = [relative[0], relative[1], 0];
  else if (mode === "descend") {
    const horizontal = unit([initialVelocity[0], initialVelocity[1], 0]);
    desired = [horizontal[0] * Math.cos(30 * RAD), horizontal[1] * Math.cos(30 * RAD), -Math.sin(30 * RAD)];
  } else return velocity;
  return rotateToward(velocity, desired, acceleration / length(velocity) * dt);
}

export function validateEncounter(input, weapon) {
  const bounds = { rangeM: [200, 30000], targetSpeedMps: [100, 650], missileSpeedMps: [200, 2000],
    targetAltitudeM: [0, 18000], missileAltitudeM: [0, 20000], aspectDeg: [0, 180],
    flightPathDeg: [-45, 45], targetG: [1, 12], delayS: [0, 15],
    observationGapS: [0, 10], missileAgeS: [0, 120] };
  if (Object.entries(bounds).some(([key, [lo, hi]]) => !Number.isFinite(input[key]) || input[key] < lo || input[key] > hi)) {
    return "请在标示范围内填写完整数值。";
  }
  if (Math.abs(input.targetAltitudeM - input.missileAltitudeM) >= input.rangeM) return "斜距必须大于双方高度差。";
  if (weapon && input.missileAgeS >= weapon.lifetimeS) return `已飞行时间须小于本弹配置寿命 ${weapon.lifetimeS} s。`;
  return null;
}

export function simulateEncounter(weapon, input, mode, { stepS = 1 / 120, horizonS = 30 } = {}) {
  const invalid = validateEncounter(input, weapon);
  if (invalid) throw new RangeError(invalid);
  if (!["straight", "beam", "cold", "descend"].includes(mode)) throw new RangeError("unknown maneuver");
  if (!(stepS > 0 && stepS <= .1) || !(horizonS > 0 && horizonS <= 60)) throw new RangeError("invalid integration interval");
  const remainingLifeS = weapon.lifetimeS - input.missileAgeS;
  const durationLimitS = Math.min(horizonS, remainingLifeS);
  const dh = input.targetAltitudeM - input.missileAltitudeM;
  let target = [Math.sqrt(input.rangeM ** 2 - dh ** 2), 0, input.targetAltitudeM];
  let missile = [0, 0, input.missileAltitudeM];
  const gamma = input.flightPathDeg * RAD, aspect = input.aspectDeg * RAD;
  const initialVelocity = scale([Math.cos(gamma) * Math.cos(aspect), Math.cos(gamma) * Math.sin(aspect), Math.sin(gamma)], input.targetSpeedMps);
  let targetVelocity = initialVelocity;
  const lead = interceptVelocity(sub(target, missile), targetVelocity, input.missileSpeedMps);
  let missileVelocity = lead?.velocity ?? scale(unit(sub(target, missile)), input.missileSpeedMps);
  const initial = encounterGeometry(sub(target, missile), targetVelocity, missileVelocity);
  let rememberedPosition = target, rememberedVelocity = targetVelocity, rememberedTime = 0;
  let nearestM = input.rangeM, nearestTimeS = 0, peakRequestedG = 0, saturatedS = 0;
  let recovery = null, reason = remainingLifeS <= horizonS ? "lifetime" : "horizon", nextSampleS = 0, timeS = 0;
  const samples = [];
  const gapEnd = input.delayS + input.observationGapS;
  const save = (t, geometry, request, observation) => samples.push({ t,
    target: [...target], missile: [...missile], rangeM: geometry.rangeM,
    radialMps: geometry.targetRadialMps, losRateDegS: geometry.losRateDegS,
    commandG: Math.min(request.requestedG, weapon.commandLimitG),
    requestedG: request.requestedG, observation });

  for (; timeS < durationLimitS - 1e-8;) {
    const dt = Math.min(stepS, durationLimitS - timeS);
    const relative = sub(target, missile);
    const geometry = encounterGeometry(relative, targetVelocity, missileVelocity);
    const inGap = input.observationGapS > 0 && timeS >= input.delayS && timeS < gapEnd;
    let observedTarget = target, observedVelocity = targetVelocity;
    if (inGap) {
      observedTarget = add(rememberedPosition, scale(rememberedVelocity, timeS - rememberedTime));
      observedVelocity = rememberedVelocity;
    } else {
      if (input.observationGapS > 0 && timeS >= gapEnd && !recovery) {
        const prediction = add(rememberedPosition, scale(rememberedVelocity, timeS - rememberedTime));
        const predicted = encounterGeometry(sub(prediction, missile), rememberedVelocity, missileVelocity);
        recovery = { timeS, positionErrorM: length(sub(target, prediction)),
          rangeResidualM: geometry.rangeM - predicted.rangeM,
          speedResidualMps: predicted.closingMps - geometry.closingMps,
          angleResidualDeg: Math.acos(clamp(dot(predicted.los, geometry.los), -1, 1)) / RAD,
          // SARH needs the illuminating aircraft as a second endpoint.
          comparable: weapon.kind === "ARH" };
      }
      rememberedPosition = [...target]; rememberedVelocity = [...targetVelocity]; rememberedTime = timeS;
    }
    const observed = encounterGeometry(sub(observedTarget, missile), observedVelocity, missileVelocity);
    const command = guidanceCommand(weapon, observed, missileVelocity, input.missileAgeS + timeS);
    peakRequestedG = Math.max(peakRequestedG, command.requestedG);
    if (command.limited) saturatedS += dt;
    if (timeS + 1e-8 >= nextSampleS) { save(timeS, geometry, command, !inGap); nextSampleS += .05; }
    const newTargetVelocity = timeS >= input.delayS
      ? targetStep(targetVelocity, relative, initialVelocity, mode, input.targetG * G, dt) : targetVelocity;
    const acceleration = command.acceleration;
    const turn = length(acceleration) / input.missileSpeedMps * dt;
    const newMissileVelocity = turn > 1e-12
      ? add(scale(missileVelocity, Math.cos(turn)), scale(unit(acceleration), input.missileSpeedMps * Math.sin(turn)))
      : missileVelocity;
    const nextTarget = add(target, scale(add(targetVelocity, newTargetVelocity), dt / 2));
    const nextMissile = add(missile, scale(add(missileVelocity, newMissileVelocity), dt / 2));
    const nextRelative = sub(nextTarget, nextMissile), segment = sub(nextRelative, relative);
    const fraction = clamp(-dot(relative, segment) / Math.max(dot(segment, segment), 1e-12), 0, 1);
    const closest = length(add(relative, scale(segment, fraction)));
    if (closest < nearestM) { nearestM = closest; nearestTimeS = timeS + fraction * dt; }
    target = nextTarget; missile = nextMissile;
    targetVelocity = newTargetVelocity; missileVelocity = newMissileVelocity;
    timeS += dt;
    if (target[2] < 0 || missile[2] < 0) { reason = "ground"; break; }
    if (nearestM < 1) { reason = "intersection"; break; }
    if (timeS > nearestTimeS + 1.5 && geometry.closingMps < 0) { reason = "passed"; break; }
  }
  const finalGeometry = encounterGeometry(sub(target, missile), targetVelocity, missileVelocity);
  save(timeS, finalGeometry, { requestedG: 0 }, !(timeS >= input.delayS && timeS < gapEnd));
  return { mode, initial, initialLeadTimeS: lead?.timeS ?? null, samples,
    nearestM, nearestTimeS, peakRequestedG, saturatedS, recovery, reason,
    durationS: samples.at(-1).t, minimumTurnRadiusM: input.missileSpeedMps ** 2 / (weapon.commandLimitG * G) };
}

// Bounded interpolation of launch-condition tables. Target velocity here is an
// actual radial Mach input, not aspect multiplied by an assumed target speed.
export function launchReference(weapon, altitudeM, fighterMach, targetRadialMach) {
  const tables = weapon.envelope?.tables;
  if (!tables?.length || ![altitudeM, fighterMach, targetRadialMach].every(Number.isFinite)) return null;
  const sorted = [...tables].sort((a, b) => a.altitude_m - b.altitude_m);
  if (altitudeM < sorted[0].altitude_m || altitudeM > sorted.at(-1).altitude_m) return null;
  const upper = sorted.findIndex(table => table.altitude_m >= altitudeM);
  const lower = sorted[upper].altitude_m === altitudeM ? upper : upper - 1;
  const at = (table, field) => {
    const xs = table.fighter_mach, cells = table[field];
    if (!cells || fighterMach < Math.min(...xs) || fighterMach > Math.max(...xs)) return null;
    const fraction = (fighterMach - xs[0]) / (xs[1] - xs[0]);
    const row = index => {
      const first = table.target_mach[index], second = first * table.target_mach2_mult;
      if (targetRadialMach < Math.min(first, second) - 1e-9 || targetRadialMach > Math.max(first, second) + 1e-9) return null;
      const t = (targetRadialMach - first) / (second - first);
      return cells[index * 2] + t * (cells[index * 2 + 1] - cells[index * 2]);
    };
    const a = row(0), b = row(1);
    if (fraction === 0) return a;
    if (fraction === 1) return b;
    return a === null || b === null ? null : a + fraction * (b - a);
  };
  const result = {};
  for (const [name, field] of [["minRangeM", "range_min_m"], ["maxRangeM", "range_max_m"], ["tableTimeS", "time_max_s"]]) {
    const a = at(sorted[lower], field), b = at(sorted[upper], field);
    if (a === null || b === null) return null;
    const f = lower === upper ? 0 : (altitudeM - sorted[lower].altitude_m) / (sorted[upper].altitude_m - sorted[lower].altitude_m);
    result[name] = a + f * (b - a);
  }
  return result;
}
