/**
 * Карточка «оборудование не найдено» — по данным no_match_analysis из search-equipment.
 */

function buildBlockingSummary(analysis) {
  const blocking = analysis?.blocking_parameters;
  if (Array.isArray(blocking) && blocking.length > 0) {
    const parts = blocking.map((b) => b.user_value).filter(Boolean);
    if (parts.length) {
      return `Нет моделей с: ${parts.join('; ')}`;
    }
  }
  return analysis?.short_reason || '';
}

function StatusBadge({ status, onRetry, disabled }) {
  const isFail = status === 'fail';
  if (isFail && typeof onRetry === 'function') {
    return (
      <button
        type="button"
        className="eq-no-match__badge eq-no-match__badge--fail eq-no-match__badge--btn"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onRetry();
        }}
        disabled={disabled}
        aria-label="Ввести параметры заново"
        title="Ввести параметры заново"
      >
        ✕
      </button>
    );
  }
  if (isFail) {
    return (
      <span className="eq-no-match__badge eq-no-match__badge--fail" aria-hidden="true">
        ✕
      </span>
    );
  }
  return (
    <span className="eq-no-match__badge eq-no-match__badge--ok" aria-hidden="true">
      ✓
    </span>
  );
}

function ParameterTile({ param, onRetry, editBusy }) {
  const isFail = param.status === 'fail';
  const canRetry = typeof onRetry === 'function';

  const handleTileClick = () => {
    if (canRetry && !editBusy) {
      onRetry();
    }
  };

  return (
    <div
      className={`eq-no-match__tile${isFail ? ' eq-no-match__tile--fail' : ' eq-no-match__tile--ok'}${
        canRetry ? ' eq-no-match__tile--interactive' : ''
      }`}
      role={canRetry ? 'button' : undefined}
      tabIndex={canRetry ? 0 : undefined}
      onClick={canRetry ? handleTileClick : undefined}
      onKeyDown={
        canRetry
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                handleTileClick();
              }
            }
          : undefined
      }
      title={canRetry ? 'Ввести параметры заново' : undefined}
    >
      <StatusBadge status={param.status} disabled={editBusy} onRetry={canRetry ? onRetry : undefined} />
      <span className="eq-no-match__tile-icon" aria-hidden="true">
        {param.icon || '•'}
      </span>
      <span className="eq-no-match__tile-label">{param.label}</span>
      <span className="eq-no-match__tile-value">{param.value}</span>
      {isFail && param.catalog_range ? (
        <span className="eq-no-match__tile-range">{param.catalog_range}</span>
      ) : null}
    </div>
  );
}

export function EquipmentNoMatchCard({ analysis, onRetry, editBusy = false }) {
  if (!analysis || typeof analysis !== 'object') return null;

  const parameters = Array.isArray(analysis.parameters) ? analysis.parameters : [];
  const blockingSummary = buildBlockingSummary(analysis);

  return (
    <div className="eq-no-match" role="region" aria-label="Оборудование не найдено">
      <div className="eq-no-match__hero">
        <div className="eq-no-match__hero-icon" aria-hidden="true">
          🔍
        </div>
        <h3 className="eq-no-match__hero-title">Не найдено</h3>
        <p className="eq-no-match__hero-sub">Выберите подходящее оборудование</p>
      </div>

      <div className="eq-no-match__emoji" aria-hidden="true">
        😔
      </div>
      <p className="eq-no-match__summary">
        {analysis.summary || 'Оборудование с выбранными параметрами не найдено'}
      </p>

      {parameters.length > 0 ? (
        <div className="eq-no-match__grid">
          {parameters.map((param) => (
            <ParameterTile
              key={param.key || param.label}
              param={param}
              onRetry={onRetry}
              editBusy={editBusy}
            />
          ))}
        </div>
      ) : null}

      {blockingSummary ? <p className="eq-no-match__blocking">{blockingSummary}</p> : null}

      <p className="eq-no-match__hint">
        Измените параметры, отмеченные красным, и попробуйте снова
      </p>

      {typeof onRetry === 'function' ? (
        <button
          type="button"
          className="eq-no-match__retry-btn"
          onClick={onRetry}
          disabled={editBusy}
        >
          Ввести параметры заново
        </button>
      ) : null}
    </div>
  );
}

export { buildBlockingSummary };
