/** Original short earcons: pitch direction identifies the event; rhythm conveys urgency. */
export type SoundCuePreset = "classic" | "chime" | "low";
export type SoundCueKind = "timer" | "zone-destroyed" | "overspeed";

export interface CueNote {
  readonly frequencyHz: number;
  readonly delayMs: number;
  readonly durationMs: number;
  readonly peak: number;
  readonly waveform: "sine" | "triangle";
}

export function soundCueNotes(kind: SoundCueKind, preset: SoundCuePreset, urgent = false): readonly CueNote[] {
  const note = (frequencyHz: number, delayMs: number, durationMs: number, peak = 0.075, waveform: CueNote["waveform"] = "sine"): CueNote =>
    ({ frequencyHz, delayMs, durationMs, peak, waveform });
  if (kind === "overspeed") {
    // The same descending fourth remains recognisable at both urgency levels.
    return urgent
      ? [note(880, 0, 125, 0.085, "triangle"), note(659.25, 145, 155, 0.085, "triangle")]
      : [note(880, 0, 180, 0.065), note(659.25, 210, 230, 0.065)];
  }
  const root = preset === "low" ? 349.23 : preset === "chime" ? 698.46 : 523.25;
  if (kind === "zone-destroyed") {
    return [note(root, 0, 240, 0.065), note(root * 1.5, 190, 330, 0.06)];
  }
  const pitch = root * (urgent ? 1.25 : 1);
  return preset === "chime"
    ? [note(pitch, 0, 120, 0.055), note(pitch * 1.5, 100, 160, 0.04)]
    : [note(pitch, 0, urgent ? 140 : 190)];
}

/** Used by live cues and OfflineAudioContext auditions, so previews render the actual sound. */
export function scheduleSoundCue(
  context: BaseAudioContext,
  notes: readonly CueNote[],
  ended: (voice: OscillatorNode) => void = () => {},
): readonly OscillatorNode[] {
  const startsAt = context.currentTime;
  return notes.map(note => {
    const voice = context.createOscillator();
    const gain = context.createGain();
    const start = startsAt + note.delayMs / 1000;
    const end = start + note.durationMs / 1000;
    voice.type = note.waveform;
    voice.frequency.value = note.frequencyHz;
    // Soft attack, early decay, and a zero tail remove the hard-edged old beep.
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(note.peak, start + 0.014);
    gain.gain.exponentialRampToValueAtTime(note.peak * 0.42, start + note.durationMs / 4000);
    gain.gain.exponentialRampToValueAtTime(0.0001, end - 0.012);
    gain.gain.linearRampToValueAtTime(0, end);
    voice.connect(gain).connect(context.destination);
    voice.onended = () => { voice.disconnect(); gain.disconnect(); ended(voice); };
    voice.start(start);
    voice.stop(end);
    return voice;
  });
}
