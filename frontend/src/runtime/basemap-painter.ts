/** Presentation-only callback; the host owns official map-image acquisition. */
export type BasemapPainter = (context: CanvasRenderingContext2D, rect: { x: number; y: number; width: number; height: number }) => void;
