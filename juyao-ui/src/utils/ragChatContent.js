/** 从助手回复中拆分 think 与正文（支持 think / redacted_thinking / thinking 标签）。 */

const OPEN_RE = /<(think|redacted_thinking|thinking)>/i
const CLOSE_RE = /<\/(think|redacted_thinking|thinking)>/i

export function splitThinkContent(raw) {
  const text = raw || ''
  const openMatch = text.match(OPEN_RE)
  if (!openMatch) {
    return { think: '', answer: text, inThink: false, thinkDone: true }
  }
  const start = openMatch.index + openMatch[0].length
  const rest = text.slice(start)
  const closeMatch = rest.match(CLOSE_RE)
  if (!closeMatch) {
    return { think: rest, answer: '', inThink: true, thinkDone: false }
  }
  const think = rest.slice(0, closeMatch.index)
  const answer = rest.slice(closeMatch.index + closeMatch[0].length).trimStart()
  return { think, answer, inThink: false, thinkDone: true }
}
