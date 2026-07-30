/** ID helper safe on HTTP (non-secure context), e.g. ECS without TLS. */
export function safeRandomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    try {
      return crypto.randomUUID()
    } catch {
      /* secure-context only in some browsers */
    }
  }
  return `id-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`
}
