import { useEffect, useState, useCallback, useMemo } from 'react';
import { getGrandGasMetersPrices, postGrandGasMetersPrices } from '../api';

const UFG_H_SECTION = {
  id: 'ufg-h',
  label: 'UFG-H',
  icon: '⚙️',
  headIcon: '⚙️',
  parentTab: null,
  ready: false,
};

const SECTION_META = {
  grand: { label: 'СГ Гранд', icon: '🔥', headIcon: '💧', parentTab: 'СГ Гранд' },
  grand_spi: { label: 'СГ Гранд SPI', icon: '📡', headIcon: '📡', parentTab: 'СГ Гранд SPI' },
};

const FALLBACK_SPI_CHILD_TABS = [
  { id: '150', title: 'до 150 кПа (−20 °C … +60 °C)' },
  { id: '5k-40', title: '5 кПа (−40 °C … +60 °C)' },
  { id: '5k-20', title: '5 кПа (−20 °C … +60 °C)' },
];

function formatRub(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value ?? '');
  return new Intl.NumberFormat('ru-RU').format(n);
}

function formatLoadError(err) {
  const d = err?.response?.data;
  if (typeof d === 'string' && d.trim()) return d;
  if (d?.detail != null && typeof d.detail === 'string') return d.detail;
  if (Array.isArray(d?.detail)) return d.detail.map((x) => String(x)).join('; ');
  if (d?.message) return String(d.message);
  if (err?.message) return String(err.message);
  return 'Не удалось загрузить прайс';
}

function normalizePriceItem(row) {
  const price = Number(row?.price_rub ?? row?.price) || 0;
  return {
    name: row?.name || '',
    price,
    priceDisplay: row?.price_display || null,
  };
}

function itemKey(row) {
  return `${row?.name || ''}::${row?.price ?? ''}`;
}

function buildDisplaySections(data) {
  if (!data) return [];
  const sections = Array.isArray(data.sections) ? data.sections : [];
  if (sections.length > 0) {
    if (sections.length === 1 && sections[0].id === 'all') {
      const items = (sections[0].items || data.items || []).map(normalizePriceItem);
      return items.length ? [{ id: 'all', title: null, items }] : [];
    }
    return sections
      .map((section) => ({
        id: section.id || section.title,
        title: section.title || null,
        items: (section.items || []).map(normalizePriceItem),
      }))
      .filter((section) => section.items.length > 0);
  }
  const items = (data.items || []).map(normalizePriceItem);
  return items.length ? [{ id: 'all', title: null, items }] : [];
}

/**
 * Карточка прайса бытовых счётчиков (GET catalog + POST parent_tab / child_tab).
 */
export function GrandGasMetersPriceBlock({ onLeaveRequest }) {
  const [catalog, setCatalog] = useState(null);
  const [activeSectionId, setActiveSectionId] = useState('grand');
  const [activeSpiChildId, setActiveSpiChildId] = useState('150');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedItems, setSelectedItems] = useState([]);
  const [expandedSpiSectionId, setExpandedSpiSectionId] = useState(null);

  const parentSections = useMemo(() => {
    const parents = Array.isArray(catalog?.parents) ? catalog.parents : [];
    const fromCatalog = parents.map((parent) => {
      const meta = SECTION_META[parent.id] || {};
      return {
        id: parent.id === 'grand_spi' ? 'grand-spi' : parent.id,
        apiId: parent.id,
        label: meta.label || parent.title,
        icon: meta.icon || '📋',
        headIcon: meta.headIcon || '📋',
        parentTab: meta.parentTab || parent.title,
        childTabs: parent.child_tabs || [],
      };
    });
    return [...fromCatalog, UFG_H_SECTION];
  }, [catalog]);

  const activeSection = useMemo(
    () => parentSections.find((section) => section.id === activeSectionId) || parentSections[0],
    [activeSectionId, parentSections]
  );

  const spiChildTabs = useMemo(() => {
    const spi = parentSections.find((section) => section.id === 'grand-spi');
    const tabs = spi?.childTabs?.length ? spi.childTabs : FALLBACK_SPI_CHILD_TABS;
    return tabs;
  }, [parentSections]);

  const activeSpiChild = useMemo(
    () => spiChildTabs.find((tab) => tab.id === activeSpiChildId) || spiChildTabs[0],
    [activeSpiChildId, spiChildTabs]
  );

  const loadCatalog = useCallback(async () => {
    try {
      const res = await getGrandGasMetersPrices();
      setCatalog(res.data?.catalog || null);
      return res.data;
    } catch {
      return null;
    }
  }, []);

  const loadPrices = useCallback(async () => {
    if (activeSectionId === 'ufg-h') {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      if (activeSectionId === 'grand') {
        const res = await postGrandGasMetersPrices({ parent_tab: 'СГ Гранд' });
        setData(res.data || null);
      } else if (activeSectionId === 'grand-spi') {
        const childTab = activeSpiChild?.id || activeSpiChildId;
        const res = await postGrandGasMetersPrices({
          parent_tab: 'СГ Гранд SPI',
          child_tab: childTab,
        });
        setData(res.data || null);
      }
    } catch (e) {
      setError(formatLoadError(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [activeSectionId, activeSpiChild, activeSpiChildId]);

  useEffect(() => {
    loadCatalog();
  }, [loadCatalog]);

  useEffect(() => {
    loadPrices();
  }, [loadPrices]);

  useEffect(() => {
    setSelectedItems([]);
  }, [activeSectionId, activeSpiChildId]);

  const displaySections = useMemo(() => buildDisplaySections(data), [data]);
  const showSpiAccordion = activeSectionId === 'grand-spi' && displaySections.some((section) => section.title);

  useEffect(() => {
    if (!showSpiAccordion || displaySections.length === 0) {
      setExpandedSpiSectionId(null);
      return;
    }
    setExpandedSpiSectionId((prev) => {
      if (prev && displaySections.some((section) => section.id === prev)) {
        return prev;
      }
      return displaySections[0].id;
    });
  }, [showSpiAccordion, displaySections, activeSpiChildId]);
  const flatItemCount = useMemo(
    () => displaySections.reduce((sum, section) => sum + section.items.length, 0),
    [displaySections]
  );

  const title = data?.title || (activeSectionId === 'grand-spi' ? 'Прайс-лист на СГ Гранд SPI' : activeSection?.label);
  const subtitle = data?.subtitle || (activeSectionId === 'ufg-h' ? 'Раздел в разработке' : '');
  const note = data?.note || null;
  const priceColumnTitle = data?.price_column_title || 'Цена, ₽';
  const showPriceTable = activeSectionId !== 'ufg-h';
  const showSpiSubNav = activeSectionId === 'grand-spi';
  const showStub = activeSectionId === 'ufg-h';

  const selectedByKey = useMemo(() => {
    const map = new Map();
    selectedItems.forEach((item) => {
      map.set(itemKey(item), item);
    });
    return map;
  }, [selectedItems]);

  const changeQuantity = useCallback((row, delta) => {
    const key = itemKey(row);
    setSelectedItems((prev) => {
      const existing = prev.find((item) => itemKey(item) === key);
      if (!existing) {
        if (delta <= 0) return prev;
        return [
          ...prev,
          {
            name: row.name || '',
            price: Number(row.price) || 0,
            quantity: 1,
          },
        ];
      }

      const nextQuantity = existing.quantity + delta;
      if (nextQuantity <= 0) {
        return prev.filter((item) => itemKey(item) !== key);
      }
      return prev.map((item) =>
        itemKey(item) === key
          ? {
              ...item,
              quantity: nextQuantity,
            }
          : item
      );
    });
  }, []);

  const selectRow = useCallback(
    (row) => {
      if (!selectedByKey.has(itemKey(row))) {
        changeQuantity(row, 1);
      }
    },
    [changeQuantity, selectedByKey]
  );

  const toggleSpiSection = useCallback((sectionId) => {
    setExpandedSpiSectionId((prev) => (prev === sectionId ? null : sectionId));
  }, []);

  const renderPriceRow = (row, index, options = {}) => {
    const { spiTable = false } = options;
    const selected = selectedByKey.get(itemKey(row));
    return (
      <li
        key={`${index}-${row.name || ''}`}
        className={`grand-gas-price-block__row${spiTable ? ' grand-gas-price-block__row--spi' : ''} ${
          index % 2 === 1 ? 'grand-gas-price-block__row--alt' : ''
        } ${selected ? 'grand-gas-price-block__row--selected' : ''}`}
        role="button"
        tabIndex={0}
        aria-pressed={Boolean(selected)}
        onClick={() => selectRow(row)}
        onKeyDown={(ev) => {
          if (ev.key === 'Enter' || ev.key === ' ') {
            ev.preventDefault();
            selectRow(row);
          }
        }}
      >
        {!spiTable ? <span className="grand-gas-price-block__num">{index + 1}</span> : null}
        <span className="grand-gas-price-block__name">{row.name || '—'}</span>
        <span className="grand-gas-price-block__price-cell">
          <span className="grand-gas-price-block__price">
            {row.priceDisplay || (
              <>
                {formatRub(row.price)} <span className="grand-gas-price-block__rub">₽</span>
              </>
            )}
          </span>
          {selected && (
            <span className="grand-gas-price-block__counter" aria-label={`Количество: ${selected.quantity}`}>
              <button
                type="button"
                className="grand-gas-price-block__counter-btn"
                onClick={(ev) => {
                  ev.stopPropagation();
                  changeQuantity(row, -1);
                }}
                aria-label="Уменьшить количество"
              >
                −
              </button>
              <span className="grand-gas-price-block__counter-value">{selected.quantity}</span>
              <button
                type="button"
                className="grand-gas-price-block__counter-btn"
                onClick={(ev) => {
                  ev.stopPropagation();
                  changeQuantity(row, 1);
                }}
                aria-label="Увеличить количество"
              >
                +
              </button>
            </span>
          )}
        </span>
      </li>
    );
  };

  let rowCounter = 0;

  const renderFlatPriceSections = () => (
    <>
      {displaySections.map((section) => (
        <div key={section.id} className="grand-gas-price-block__section">
          {section.title ? (
            <h3 className="grand-gas-price-block__section-title">{section.title}</h3>
          ) : null}
          <div className="grand-gas-price-block__thead" aria-hidden="true">
            <span>№</span>
            <span>Наименование прибора</span>
            <span>{priceColumnTitle}</span>
          </div>
          <ul className="grand-gas-price-block__list">
            {section.items.map((row) => {
              const node = renderPriceRow(row, rowCounter);
              rowCounter += 1;
              return node;
            })}
          </ul>
        </div>
      ))}
    </>
  );

  const renderSpiAccordionSections = () => (
    <div className="grand-gas-price-block__spi-sections">
      {displaySections.map((section) => {
        const isExpanded = expandedSpiSectionId === section.id;
        return (
          <div
            key={section.id}
            className={`grand-gas-price-block__spi-section${
              isExpanded ? ' grand-gas-price-block__spi-section--expanded' : ''
            }`}
          >
            <button
              type="button"
              className="grand-gas-price-block__spi-header"
              aria-expanded={isExpanded}
              onClick={() => toggleSpiSection(section.id)}
            >
              <span className="grand-gas-price-block__spi-title">{section.title}</span>
              <span className="grand-gas-price-block__spi-count">{section.items.length} поз.</span>
              <span className="grand-gas-price-block__spi-arrow" aria-hidden="true">
                ›
              </span>
            </button>
            <div className="grand-gas-price-block__spi-body">
              <div className="grand-gas-price-block__spi-table">
                <div
                  className="grand-gas-price-block__thead grand-gas-price-block__thead--spi"
                  aria-hidden="true"
                >
                  <span>Наименование</span>
                  <span>{priceColumnTitle}</span>
                </div>
                <ul className="grand-gas-price-block__list">
                  {section.items.map((row, index) => renderPriceRow(row, index, { spiTable: true }))}
                </ul>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );

  return (
    <div className="grand-gas-price-block" role="region" aria-labelledby="grand-gas-price-title">
      <div className="grand-gas-price-block__head">
        <span className="grand-gas-price-block__drop" aria-hidden="true">
          {activeSection?.headIcon || '💧'}
        </span>
        <h2 id="grand-gas-price-title" className="grand-gas-price-block__title">
          {title}
        </h2>
        {subtitle ? <p className="grand-gas-price-block__subtitle">{subtitle}</p> : null}
      </div>

      <div className="grand-gas-price-block__tabs" role="tablist" aria-label="Разделы прайс-листа">
        {(parentSections.length ? parentSections : [
          { id: 'grand', label: 'СГ Гранд', icon: '🔥' },
          { id: 'grand-spi', label: 'СГ Гранд SPI', icon: '📡' },
          UFG_H_SECTION,
        ]).map((section) => {
          const isActive = section.id === activeSectionId;
          return (
            <button
              key={section.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={`grand-gas-price-block__tab${
                isActive ? ' grand-gas-price-block__tab--active' : ''
              }`}
              onClick={() => setActiveSectionId(section.id)}
            >
              <span className="grand-gas-price-block__tab-icon" aria-hidden="true">
                {section.icon}
              </span>
              <span className="grand-gas-price-block__tab-label">{section.label}</span>
            </button>
          );
        })}
      </div>

      {showSpiSubNav && (
        <div
          className="grand-gas-price-block__subtabs"
          role="tablist"
          aria-label="Варианты СГ Гранд SPI"
        >
          {spiChildTabs.map((variant) => {
            const isActive = variant.id === activeSpiChildId;
            return (
              <button
                key={variant.id}
                type="button"
                role="tab"
                aria-selected={isActive}
                className={`grand-gas-price-block__subtab${
                  isActive ? ' grand-gas-price-block__subtab--active' : ''
                }`}
                onClick={() => setActiveSpiChildId(variant.id)}
              >
                {variant.title}
              </button>
            );
          })}
        </div>
      )}

      {showSpiSubNav && note ? <p className="grand-gas-price-block__note">{note}</p> : null}

      <div className="grand-gas-price-block__scroll">
        {showStub && <div className="grand-gas-price-block__stub">В разработке</div>}
        {showPriceTable && loading && <div className="grand-gas-price-block__status">Загрузка прайса…</div>}
        {showPriceTable && error && !loading && (
          <div className="grand-gas-price-block__error">
            {error}
            <button type="button" className="grand-gas-price-block__retry" onClick={loadPrices}>
              Повторить
            </button>
          </div>
        )}
        {showPriceTable && !loading && !error && flatItemCount === 0 && (
          <div className="grand-gas-price-block__status">Нет позиций в прайсе.</div>
        )}
        {showPriceTable && !loading && !error && flatItemCount > 0 && (
          showSpiAccordion ? renderSpiAccordionSections() : renderFlatPriceSections()
        )}
      </div>

      {showPriceTable && (
        <button
          type="button"
          className="grand-gas-price-block__cta"
          onClick={() => {
            const payload = { selected_items: selectedItems };
            onLeaveRequest?.(payload);
          }}
        >
          Оставить заявку →
        </button>
      )}
    </div>
  );
}
