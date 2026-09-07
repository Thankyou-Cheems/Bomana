export type EditionChannel = "Lite" | "Standard" | "Enhanced";

export interface EditionCapabilities {
  readonly timer: boolean;
  readonly speed: boolean;
  readonly missionAlerts: boolean;
  readonly zoneNavigation: boolean;
  readonly airfieldNavigation: boolean;
  readonly extendedNavigationTargets: boolean;
  readonly airfieldModuleNavigation: boolean;
  readonly tacticalMapCoordinates: boolean;
  readonly y66Calibration: boolean;
  readonly automaticChatRecognition: boolean;
  readonly zoneCountdown: boolean;
  readonly terrainElevation: boolean;
  readonly fuel: boolean;
  readonly checklist: boolean;
  readonly advancedSettings: boolean;
  readonly pictureInPicture: boolean;
  readonly mobilePairing: boolean;
  readonly strikePrediction: boolean;
  readonly strikeEncyclopedia: boolean;
}
export interface EditionPolicy {
  readonly channel: EditionChannel;
  readonly displayName: string;
  readonly access: "public" | "subscription";
  readonly capabilities: EditionCapabilities;
}

export const EDITION_POLICIES: Readonly<Record<EditionChannel, EditionPolicy>> = Object.freeze({
  Lite: Object.freeze({
    channel: "Lite",
    displayName: "精简版",
    access: "public",
    capabilities: Object.freeze({
      timer: true,
      speed: false,
      missionAlerts: false,
      advancedSettings: false,
      strikeEncyclopedia: false,
      zoneNavigation: false,
      airfieldNavigation: false,
      extendedNavigationTargets: false,
      airfieldModuleNavigation: false,
      tacticalMapCoordinates: false,
      y66Calibration: false,
      automaticChatRecognition: false,
      zoneCountdown: false,
      terrainElevation: false,
      fuel: false,
      checklist: false,
      pictureInPicture: false,
      mobilePairing: false,
      strikePrediction: false,
    }),
  }),
  Standard: Object.freeze({
    channel: "Standard",
    displayName: "标准版",
    access: "public",
    capabilities: Object.freeze({
      timer: true,
      speed: true,
      missionAlerts: true,
      advancedSettings: true,
      strikeEncyclopedia: true,
      zoneNavigation: true,
      airfieldNavigation: true,
      extendedNavigationTargets: false,
      airfieldModuleNavigation: false,
      tacticalMapCoordinates: false,
      y66Calibration: false,
      automaticChatRecognition: false,
      zoneCountdown: false,
      terrainElevation: false,
      fuel: true,
      checklist: true,
      pictureInPicture: true,
      mobilePairing: true,
      strikePrediction: false,
    }),
  }),
  Enhanced: Object.freeze({
    channel: "Enhanced",
    displayName: "超级爆弹版",
    access: "subscription",
    capabilities: Object.freeze({
      timer: true,
      speed: true,
      missionAlerts: true,
      advancedSettings: true,
      strikeEncyclopedia: true,
      zoneNavigation: true,
      airfieldNavigation: true,
      extendedNavigationTargets: true,
      airfieldModuleNavigation: true,
      tacticalMapCoordinates: true,
      y66Calibration: true,
      automaticChatRecognition: true,
      zoneCountdown: true,
      terrainElevation: true,
      fuel: true,
      checklist: true,
      pictureInPicture: true,
      mobilePairing: true,
      strikePrediction: true,
    }),
  }),
});

export function editionPolicy(channel: string): EditionPolicy {
  if (channel === "Lite" || channel === "Standard" || channel === "Enhanced") {
    return EDITION_POLICIES[channel];
  }
  throw new TypeError(`unknown Bomana edition: ${channel}`);
}
