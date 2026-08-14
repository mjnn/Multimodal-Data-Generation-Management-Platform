/** Map bbox coords between native frame pixels and preview-MP4 canvas (long-edge fit). */

export type Size = { width: number; height: number }

export type LongEdgeFit = {
  scale: number
  cropLeft: number
  cropTop: number
  offsetX: number
  offsetY: number
  contentW: number
  contentH: number
  canvasW: number
  canvasH: number
  nativeW: number
  nativeH: number
}

/** Same geometry as ``oms_multimodal.clip_video._long_edge_fit_image``. */
export function computeLongEdgeFit(native: Size, canvas: Size): LongEdgeFit | null {
  const iw = native.width
  const ih = native.height
  const cw = canvas.width
  const ch = canvas.height
  if (iw <= 0 || ih <= 0 || cw <= 0 || ch <= 0) return null

  const srcLong = Math.max(iw, ih)
  const tgtLong = Math.max(cw, ch)
  const scale = tgtLong / srcLong
  let newW = Math.max(1, Math.round(iw * scale))
  let newH = Math.max(1, Math.round(ih * scale))
  let cropLeft = 0
  let cropTop = 0
  if (newW > cw || newH > ch) {
    cropLeft = Math.max(0, Math.floor((newW - cw) / 2))
    cropTop = Math.max(0, Math.floor((newH - ch) / 2))
    newW = Math.min(newW, cw)
    newH = Math.min(newH, ch)
  }
  const offsetX = Math.floor((cw - newW) / 2)
  const offsetY = Math.floor((ch - newH) / 2)
  return {
    scale,
    cropLeft,
    cropTop,
    offsetX,
    offsetY,
    contentW: newW,
    contentH: newH,
    canvasW: cw,
    canvasH: ch,
    nativeW: iw,
    nativeH: ih,
  }
}

export function nativePointToCanvas(x: number, y: number, fit: LongEdgeFit): { x: number; y: number } {
  return {
    x: fit.offsetX + x * fit.scale - fit.cropLeft,
    y: fit.offsetY + y * fit.scale - fit.cropTop,
  }
}

export function canvasPointToNative(x: number, y: number, fit: LongEdgeFit): { x: number; y: number } {
  return {
    x: (x - fit.offsetX + fit.cropLeft) / fit.scale,
    y: (y - fit.offsetY + fit.cropTop) / fit.scale,
  }
}

export function nativeBoxToCanvas(
  box: { x1: number; y1: number; x2: number; y2: number },
  fit: LongEdgeFit,
): { x1: number; y1: number; x2: number; y2: number } {
  const a = nativePointToCanvas(box.x1, box.y1, fit)
  const b = nativePointToCanvas(box.x2, box.y2, fit)
  return { x1: a.x, y1: a.y, x2: b.x, y2: b.y }
}

export function canvasBoxToNative(
  box: { x1: number; y1: number; x2: number; y2: number },
  fit: LongEdgeFit,
): { x1: number; y1: number; x2: number; y2: number } {
  const a = canvasPointToNative(box.x1, box.y1, fit)
  const b = canvasPointToNative(box.x2, box.y2, fit)
  return { x1: a.x, y1: a.y, x2: b.x, y2: b.y }
}
