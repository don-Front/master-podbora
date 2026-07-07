import { openExternalUrl, resolveAttachmentUrl } from '../config';

function resolveSourceHref(action) {
  const href = String(action?.href || '').trim();
  if (!href) return '';
  if (/^https?:\/\//i.test(href)) return href;
  if (action?.type === 'file' || href.includes('knowledge-doc/')) {
    return resolveAttachmentUrl(href);
  }
  return href;
}

function sourceActionLabel(action) {
  if (action?.label) return action.label;
  if (action?.type === 'file') return 'Открыть PDF';
  return 'Открыть';
}

export function RagSourcesCard({ sources }) {
  const items = Array.isArray(sources) ? sources.filter(Boolean) : [];
  if (!items.length) return null;

  return (
    <div className="chat-widget__rag-sources" role="region" aria-label="Источники ответа">
      <div className="chat-widget__rag-sources-head">
        <div className="chat-widget__faq-card-kicker">Источники</div>
        <div className="chat-widget__rag-sources-title">Документы по ответу</div>
      </div>
      <div className="chat-widget__rag-sources-list">
        {items.map((source, index) => {
          const actions = Array.isArray(source.actions) ? source.actions.filter((a) => a?.href) : [];
          const primary = actions[0];
          const href = primary ? resolveSourceHref(primary) : '';
          const key = source.id || source.title || `rag-source-${index}`;

          if (!href) {
            return (
              <div className="chat-widget__rag-source chat-widget__rag-source--static" key={key}>
                <div className="chat-widget__rag-source-title">{source.title}</div>
                {source.description ? (
                  <div className="chat-widget__rag-source-desc">{source.description}</div>
                ) : null}
              </div>
            );
          }

          return (
            <a
              key={key}
              className="chat-widget__rag-source"
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(event) => {
                if (primary?.type === 'url' && /^https?:\/\//i.test(href)) {
                  event.preventDefault();
                  openExternalUrl(href);
                }
              }}
            >
              <span className="chat-widget__faq-action-badge chat-widget__faq-action-badge--file">PDF</span>
              <span className="chat-widget__rag-source-body">
                <span className="chat-widget__rag-source-title">{source.title}</span>
                {source.description ? (
                  <span className="chat-widget__rag-source-desc">{source.description}</span>
                ) : null}
                <span className="chat-widget__rag-source-action">{sourceActionLabel(primary)}</span>
              </span>
            </a>
          );
        })}
      </div>
    </div>
  );
}
