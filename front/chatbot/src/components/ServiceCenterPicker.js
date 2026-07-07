import { useEffect, useMemo, useState } from 'react';
import { fetchServiceCenters } from '../api';
import { openExternalUrl } from '../config';

function TypeIcon({ kind }) {
  if (kind === 'grand') {
    return (
      <svg viewBox="0 0 48 48" aria-hidden="true" className="chat-widget__sc-type-icon">
        <path
          d="M14 34 L24 10 L34 34 Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinejoin="round"
        />
        <circle cx="24" cy="28" r="5" fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true" className="chat-widget__sc-type-icon">
      <rect x="10" y="12" width="10" height="10" rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
      <circle cx="33" cy="17" r="6" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="M12 30 H36" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M16 36 H32" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}

export function ServiceCenterPicker({ intro }) {
  const [catalog, setCatalog] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [countryName, setCountryName] = useState('');
  const [regionName, setRegionName] = useState('');
  const [centerName, setCenterName] = useState('');

  useEffect(() => {
    let cancelled = false;
    fetchServiceCenters()
      .then((response) => {
        if (cancelled) return;
        setCatalog(response.data?.categories || {});
      })
      .catch(() => {
        if (!cancelled) setLoadError('Не удалось загрузить каталог сервисных центров.');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const category = categoryId ? catalog?.[categoryId] : null;

  const countries = category?.countries || [];

  const regions = useMemo(() => {
    if (!countryName) return [];
    const country = countries.find((item) => item.name === countryName);
    return country?.regions || [];
  }, [countries, countryName]);

  const centers = useMemo(() => {
    if (!regionName) return [];
    const region = regions.find((item) => item.name === regionName);
    return region?.centers || [];
  }, [regions, regionName]);

  const selectedCenter = centers.find((item) => item.name === centerName);

  const resetAfterCategory = (nextId) => {
    setCategoryId(nextId);
    setCountryName('');
    setRegionName('');
    setCenterName('');
  };

  const handleOpenSite = () => {
    if (!category?.pageUrl) return;
    openExternalUrl(category.pageUrl);
  };

  const handleOpenCenter = () => {
    const centerUrl = selectedCenter?.url || category?.pageUrl;
    if (!centerUrl) return;
    openExternalUrl(centerUrl);
  };

  if (loadError) {
    return <div className="chat-widget__sc-picker chat-widget__sc-picker--error">{loadError}</div>;
  }

  if (!catalog) {
    return <div className="chat-widget__sc-picker chat-widget__sc-picker--loading">Загружаю каталог…</div>;
  }

  return (
    <div className="chat-widget__sc-picker" role="region" aria-label="Подбор сервисного центра">
      <div className="chat-widget__sc-picker-head">
        <div className="chat-widget__faq-card-kicker">Справочная информация</div>
        <div className="chat-widget__sc-picker-title">{intro?.title || 'Сервисные центры'}</div>
        {intro?.description ? (
          <p className="chat-widget__sc-picker-desc">{intro.description}</p>
        ) : null}
      </div>

      {!categoryId ? (
        <div className="chat-widget__sc-type-grid">
          {Object.values(catalog).map((item) => (
            <button
              key={item.id}
              type="button"
              className="chat-widget__sc-type-card"
              onClick={() => resetAfterCategory(item.id)}
            >
              <TypeIcon kind={item.id} />
              <span className="chat-widget__sc-type-card-title">{item.title}</span>
            </button>
          ))}
        </div>
      ) : (
        <>
          <button type="button" className="chat-widget__sc-back" onClick={() => resetAfterCategory('')}>
            ← Выбрать другое направление
          </button>

          <div className="chat-widget__sc-filters">
            <label className="chat-widget__sc-field">
              <span className="chat-widget__sc-field-label">Страна</span>
              <select
                className="chat-widget__sc-select"
                value={countryName}
                onChange={(e) => {
                  setCountryName(e.target.value);
                  setRegionName('');
                  setCenterName('');
                }}
              >
                <option value="">Выберите страну</option>
                {countries.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="chat-widget__sc-field">
              <span className="chat-widget__sc-field-label">Регион</span>
              <select
                className="chat-widget__sc-select"
                value={regionName}
                disabled={!countryName}
                onChange={(e) => {
                  setRegionName(e.target.value);
                  setCenterName('');
                }}
              >
                <option value="">Выберите регион</option>
                {regions.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="chat-widget__sc-field">
              <span className="chat-widget__sc-field-label">Сервисный центр</span>
              <select
                className="chat-widget__sc-select"
                value={centerName}
                disabled={!regionName}
                onChange={(e) => setCenterName(e.target.value)}
              >
                <option value="">Выберите центр</option>
                {centers.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {selectedCenter ? (
            <button
              type="button"
              className="chat-widget__sc-result"
              onClick={handleOpenCenter}
              title="Открыть карточку сервисного центра"
            >
              <div className="chat-widget__sc-result-name">{selectedCenter.name}</div>
              <div className="chat-widget__sc-result-meta">
                {regionName}, {countryName}
              </div>
            </button>
          ) : null}

          <button type="button" className="chat-widget__sc-open-btn" onClick={handleOpenSite}>
            Открыть раздел на сайте
          </button>
        </>
      )}
    </div>
  );
}
