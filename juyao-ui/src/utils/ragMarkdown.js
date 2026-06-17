import { marked } from 'marked'
import hljs from 'highlight.js/lib/highlight'
import 'highlight.js/styles/github.css'

const LANGS = [
  'javascript', 'typescript', 'python', 'java', 'sql', 'bash', 'shell',
  'json', 'xml', 'html', 'css', 'markdown', 'yaml', 'powershell', 'dockerfile', 'ini', 'properties'
]
LANGS.forEach((lang) => {
  try {
    hljs.registerLanguage(lang, require(`highlight.js/lib/languages/${lang}`))
  } catch (e) {
    // optional language pack
  }
})

function highlightCode(code, lang) {
  const language = (lang || '').trim().toLowerCase()
  if (language && hljs.getLanguage(language)) {
    try {
      return hljs.highlight(language, code, true).value
    } catch (e) {
      // fall through
    }
  }
  try {
    return hljs.highlightAuto(code).value
  } catch (e) {
    return code
  }
}

const renderer = new marked.Renderer()

renderer.code = function(code, infostring) {
  const lang = (infostring || '').trim().split(/\s+/)[0] || 'text'
  const body = highlightCode(code, lang)
  const label = lang === 'text' ? 'code' : lang
  return (
    `<div class="md-code-block">` +
    `<div class="md-code-header"><span class="md-code-lang">${label}</span></div>` +
    `<pre><code class="hljs language-${label}">${body}</code></pre></div>`
  )
}

renderer.table = function(header, body) {
  return `<div class="md-table-wrap"><table><thead>${header}</thead><tbody>${body}</tbody></table></div>`
}

renderer.hr = function() {
  return '<hr class="md-hr" />'
}

marked.setOptions({
  gfm: true,
  breaks: true,
  headerIds: false,
  mangle: false,
  renderer
})

function bannerHtml(type, icon, title, subtitle) {
  return (
    `<div class="md-banner md-banner-${type}">` +
    `<div class="md-banner-icon">${icon}</div>` +
    `<div class="md-banner-text"><h2>${title}</h2><p>${subtitle}</p></div></div>`
  )
}

const BANNER_REPLACERS = [
  [
    /<h2>📚 知识库依据回答<\/h2>/,
    bannerHtml('kb', '📚', '知识库依据回答', '以下内容主要依据知识库检索结果整理，请结合原文核验')
  ],
  [
    /<h2>🌐 通用知识说明<\/h2>/,
    bannerHtml('general', '🌐', '通用知识说明', '知识库未命中可用片段，以下为模型通用知识，请勿当作内部权威依据')
  ],
  [
    /<h2>💡 补充说明（通用推断）<\/h2>/,
    bannerHtml('supplement', '💡', '补充说明（通用推断）', '以下部分无直接检索依据，属于谨慎推断，请自行核实')
  ]
]

function stripTags(html) {
  return html.replace(/<[^>]+>/g, '')
}

function enhanceBlockquotes(html) {
  return html.replace(/<blockquote>([\s\S]*?)<\/blockquote>/g, (match, inner) => {
    const plain = stripTags(inner)
    if (/重要提示.*知识库|知识库依据|检索结果生成|检索内容/.test(plain)) {
      return (
        `<div class="md-alert md-alert-kb">` +
        `<div class="md-alert-title">📚 知识库依据提示</div>` +
        `<div class="md-alert-body">${inner}</div></div>`
      )
    }
    if (/重要提示.*通用|通用知识|未提供.*检索|未检索/.test(plain)) {
      return (
        `<div class="md-alert md-alert-general">` +
        `<div class="md-alert-title">🌐 通用知识提示</div>` +
        `<div class="md-alert-body">${inner}</div></div>`
      )
    }
    if (/^提示[:：]/.test(plain.trim())) {
      return (
        `<div class="md-alert md-alert-kb">` +
        `<div class="md-alert-title">📚 来源提示</div>` +
        `<div class="md-alert-body">${inner}</div></div>`
      )
    }
    return `<blockquote class="md-note">${inner}</blockquote>`
  })
}

/** 模型偶发自带的重复「提示：以上回答…」段落 → 合并进醒目提示框 */
function enhancePlainTips(html) {
  return html.replace(
    /<p>\s*提示\s*[:：]\s*以上回答[^<]*<\/p>\s*(?=<div class="md-alert)/gi,
    ''
  ).replace(
    /<p>\s*提示\s*[:：]\s*以上回答[^<]*<\/p>/gi,
    (m) => {
      const inner = m.replace(/^<p>\s*提示\s*[:：]\s*/i, '').replace(/<\/p>$/, '')
      return (
        `<div class="md-alert md-alert-kb">` +
        `<div class="md-alert-title">📚 知识库依据提示</div>` +
        `<div class="md-alert-body"><p>${inner}</p></div></div>`
      )
    }
  )
}

function enhanceCitations(html) {
  return html.replace(/<p>\s*(引用\s*[:：][^<]*)<\/p>/gi, (match, body) => {
    const text = body.replace(/^引用\s*[:：]\s*/i, '')
    return (
      `<div class="md-citations">` +
      `<span class="md-citations-label">引用</span>` +
      `<span class="md-citations-body">${text}</span></div>`
    )
  })
}

/** 助手消息 Markdown → HTML；用户消息保持纯文本。 */
export function renderChatMarkdown(text) {
  const src = (text || '').trim()
  if (!src) return ''
  let html = marked.parse(src)
  BANNER_REPLACERS.forEach(([pattern, replacement]) => {
    html = html.replace(pattern, replacement)
  })
  html = enhancePlainTips(html)
  html = enhanceBlockquotes(html)
  html = enhanceCitations(html)
  return html
}
