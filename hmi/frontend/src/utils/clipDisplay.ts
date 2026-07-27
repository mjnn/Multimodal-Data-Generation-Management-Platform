/** User-facing clip title: always clip_id (avoid long scene / txt names). */
export function clipDisplayName(clip: { clip_id: string }): string {
  return clip.clip_id
}
