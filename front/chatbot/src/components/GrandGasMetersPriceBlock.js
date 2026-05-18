import { useEffect, useState, useCallback, useMemo } from 'react';
import { getGrandGasMetersPrices } from '../api';

function formatRub(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value ?? '');
  return new Intl.NumberFormat('ru-RU').format(n);
}

function formatLoadError(err) {
  const d = err?.response?.data;
  if (typeof d === 'string' && d.trim()) return d;
  if (d?.detail != null && typeof d.detail === 'string') return d.detail;
  if (d?.message) return String(d.message);
  if (err?.message) return String(err.message);
  return 'Не удалось загрузить прайс';
}

function itemKey(row) {
  return `${row?.name || ''}::${row?.price ?? ''}`;
}

/**
 * Карточка с прайсом СГ Гранд в ленте чата (данные с Django `/api/prices/grand-gas-meters` или прямой URL из env).
 */
export function GrandGasMetersPriceBlock({ onLeaveRequest }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedItems, setSelectedItems] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getGrandGasMetersPrices();
      setData(res.data || null);
    } catch (e) {
      setError(formatLoadError(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const items = Array.isArray(data?.items) ? data.items : [];
  const title = data?.title || 'Прайс-лист на СГ Гранд';
  const subtitle = data?.subtitle || 'Стоимость в рублях без НДС (0%)';
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

  return (
    <div className="grand-gas-price-block" role="region" aria-labelledby="grand-gas-price-title">
      <div className="grand-gas-price-block__head">
        <span className="grand-gas-price-block__drop" aria-hidden="true">
          💧
        </span>
        <h2 id="grand-gas-price-title" className="grand-gas-price-block__title">
          {title}
        </h2>
        <p className="grand-gas-price-block__subtitle">{subtitle}</p>
      </div>

      <div className="grand-gas-price-block__scroll">
        {loading && <div className="grand-gas-price-block__status">Загрузка прайса…</div>}
        {error && !loading && (
          <div className="grand-gas-price-block__error">
            {error}
            <button type="button" className="grand-gas-price-block__retry" onClick={load}>
              Повторить
            </button>
          </div>
        )}
        {!loading && !error && items.length === 0 && (
          <div className="grand-gas-price-block__status">Нет позиций в прайсе.</div>
        )}
        {!loading && !error && items.length > 0 && (
          <>
            <div className="grand-gas-price-block__thead" aria-hidden="true">
              <span>№</span>
              <span>Наименование прибора</span>
              <span>Цена, ₽</span>
            </div>
            <ul className="grand-gas-price-block__list">
              {items.map((row, i) => {
                const selected = selectedByKey.get(itemKey(row));
                return (
                  <li
                    key={`${i}-${row.name || ''}`}
                    className={`grand-gas-price-block__row ${i % 2 === 1 ? 'grand-gas-price-block__row--alt' : ''} ${
                      selected ? 'grand-gas-price-block__row--selected' : ''
                    }`}
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
                    <span className="grand-gas-price-block__num">{i + 1}</span>
                    <span className="grand-gas-price-block__name">{row.name || '—'}</span>
                    <span className="grand-gas-price-block__price-cell">
                      <span className="grand-gas-price-block__price">
                        {formatRub(row.price)} <span className="grand-gas-price-block__rub">₽</span>
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
              })}
            </ul>
          </>
        )}
      </div>

      <button
        type="button"
        className="grand-gas-price-block__cta"
        onClick={() => {
          const payload = { selected_items: selectedItems };
          // eslint-disable-next-line no-console
          console.log('grand-gas selected_items', payload);
          onLeaveRequest?.(payload);
        }}
      >
        Оставить заявку →
      </button>
    </div>
  );
}
