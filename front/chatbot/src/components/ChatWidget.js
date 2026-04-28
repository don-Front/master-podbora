import { useEffect, useState, useCallback, useRef } from 'react';
import {
  createChat,
  createMessage,
  finalizeChat,
  getHints,
  postEquipmentSpecsTo1c,
  postEstimatePrice,
  postTkpAccessories,
  postTkpPdf,
  transitionHints,
} from '../api';
import { API_BASE_URL, resolveEquipmentImageUrl, TKP_PDF_URL } from '../config';
import { FALLBACK_HINTS_START } from '../data/fallbackHintsStart';
import { formatTime } from '../utils/formatTime';

function isOrderFinalWithSpecs(data) {
  return data?.hint_state?.current_state === 'order_final' && data?.order_specs_json != null;
}

function logIfVerificationPassed(data) {
  if (data?.verification_passed) {
    console.log('Верификация пройдена!');
  }
}

function numberFromSpecValue(value) {
  if (value == null || value === '') return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const match = String(value).match(/(\d+(?:[.,]\d+)?)/);
  return match ? Number(match[1].replace(',', '.')) : null;
}

function jsonNumber(value) {
  return Number.isInteger(value) ? value : value;
}

const TKP_MOCK_PHONE = '89289891111';
const TKP_MOCK_EMAIL = 'ustavitskyandrei@yandex.ru';

function buildEstimatePriceBody(equipment, specs) {
  const id = (equipment?.id ?? equipment?.equipment_id ?? '').toString().trim();
  const name = (equipment?.name || equipment?.model || '').toString().trim();
  const diameter = numberFromSpecValue(specs?.diameter);
  const pressureMax = numberFromSpecValue(specs?.pressure_max_mpa ?? specs?.pressure_max);
  const accuracy = numberFromSpecValue(specs?.accuracy);

  if (!id || !name || !diameter || !pressureMax || accuracy == null) {
    return null;
  }

  return {
    equipment: { id, name },
    dn: Math.trunc(diameter),
    pressure_max_mpa: jsonNumber(pressureMax),
    accuracy_percent: jsonNumber(accuracy),
  };
}

function buildTkpAccessoriesBody(estimateBody) {
  if (!estimateBody?.equipment?.id) return null;
  return {
    equipment: { id: estimateBody.equipment.id },
    dn: estimateBody.dn,
    pressure_max_mpa: estimateBody.pressure_max_mpa,
    accuracy_percent: estimateBody.accuracy_percent,
  };
}

function parsePriceRub(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.trunc(value);
  if (value == null) return null;
  const digits = String(value).replace(/[^\d]/g, '');
  return digits ? Number(digits) : null;
}

function pickTkpPdfCode(data) {
  if (typeof data === 'string' || typeof data === 'number') {
    return String(data).trim();
  }
  return (
    data?.code ||
    data?.file_code ||
    data?.fileCode ||
    data?.pdf_code ||
    data?.pdfCode ||
    data?.tkp_code ||
    data?.tkpCode ||
    data?.file ||
    data?.id ||
    ''
  ).toString().trim();
}

function tkpServiceOrigin() {
  try {
    return new URL(TKP_PDF_URL).origin;
  } catch {
    return 'http://127.0.0.1:8010';
  }
}

function resolveTkpAssetUrl(value) {
  if (!value) return '';
  const s = String(value).trim();
  if (/^https?:\/\//i.test(s)) return s;
  return `${tkpServiceOrigin()}/${s.replace(/^\/+/, '')}`;
}

function normalizeBase64(value) {
  let s = String(value || '').trim().replace(/^data:application\/pdf;base64,/i, '').replace(/\s/g, '');
  s = s.replace(/^"|"$/g, '').replace(/-/g, '+').replace(/_/g, '/');
  const remainder = s.length % 4;
  return remainder ? `${s}${'='.repeat(4 - remainder)}` : s;
}

function decodeMaybeUrlEncoded(value) {
  let s = String(value || '').trim().replace(/^"|"$/g, '');
  for (let i = 0; i < 2 && /%[0-9a-f]{2}/i.test(s); i += 1) {
    try {
      s = decodeURIComponent(s);
    } catch {
      break;
    }
  }
  return s;
}

function isPdfBase64(value) {
  const s = normalizeBase64(value);
  return s.length > 100 && (s.startsWith('JVBERi0') || s.startsWith('JVBER'));
}

function isRawPdf(value) {
  const s = decodeMaybeUrlEncoded(value);
  const pdfIndex = s.indexOf('%PDF');
  return pdfIndex >= 0 && pdfIndex < 1000;
}

function pickTkpPdfBase64(data, code) {
  const candidates = [
    data?.pdf_base64 ||
    data?.pdfBase64 ||
    data?.file_base64 ||
    data?.fileBase64 ||
    data?.content ||
    data?.data ||
    '',
    code,
  ];
  const raw = candidates.find((item) => isPdfBase64(item));
  if (raw) return normalizeBase64(raw);
  return isPdfBase64(code) ? normalizeBase64(code) : '';
}

function pickTkpPdfRaw(data, code) {
  const candidates = [
    data?.pdf,
    data?.pdf_text,
    data?.pdfText,
    data?.file,
    data?.content,
    data?.data,
    code,
  ];
  const raw = candidates.find((item) => isRawPdf(item));
  return raw ? decodeMaybeUrlEncoded(raw) : '';
}

function resolveTkpDownloadUrl(data, code) {
  const explicitUrl = resolveTkpAssetUrl(
    data?.download_url ||
      data?.downloadUrl ||
      data?.pdf_url ||
      data?.pdfUrl ||
      data?.file_url ||
      data?.fileUrl ||
      data?.url
  );
  if (explicitUrl) return explicitUrl;
  if (!code) return '';
  if (!isRawPdf(code) && (code.startsWith('/') || code.toLowerCase().endsWith('.pdf'))) {
    return resolveTkpAssetUrl(code);
  }
  return '';
}

function isArrayBufferLike(value) {
  return value instanceof ArrayBuffer || ArrayBuffer.isView(value);
}

function bytesFromArrayBufferLike(value) {
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  return null;
}

function pdfIndexInBytes(bytes) {
  if (!bytes) return -1;
  const limit = Math.min(bytes.length - 3, 1000);
  for (let i = 0; i < limit; i += 1) {
    if (bytes[i] === 0x25 && bytes[i + 1] === 0x50 && bytes[i + 2] === 0x44 && bytes[i + 3] === 0x46) {
      return i;
    }
  }
  return -1;
}

function textFromBytes(bytes) {
  return new TextDecoder('utf-8').decode(bytes);
}

function buildTkpPdfCard(data, headers = {}) {
  if (isArrayBufferLike(data)) {
    const bytes = bytesFromArrayBufferLike(data);
    const contentType = String(headers['content-type'] || headers['Content-Type'] || '').toLowerCase();
    const pdfIndex = pdfIndexInBytes(bytes);
    if (contentType.includes('application/pdf') || pdfIndex >= 0) {
      const pdfBytes = pdfIndex > 0 ? bytes.slice(pdfIndex) : bytes;
      return {
        code: '',
        base64: '',
        rawPdf: '',
        blob: new Blob([pdfBytes], { type: 'application/pdf' }),
        downloadUrl: '',
        previewUrl: '',
        filename: 'ТКП.pdf',
      };
    }

    const text = textFromBytes(bytes).trim();
    try {
      return buildTkpPdfCard(JSON.parse(text), headers);
    } catch {
      return buildTkpPdfCard(text, headers);
    }
  }

  const code = pickTkpPdfCode(data);
  const base64 = pickTkpPdfBase64(data, code);
  const rawPdf = base64 ? '' : pickTkpPdfRaw(data, code);
  const downloadUrl = resolveTkpDownloadUrl(data, code);
  const previewUrl = resolveTkpAssetUrl(
    data?.preview_url || data?.previewUrl || data?.image_url || data?.imageUrl || data?.thumbnail_url
  );
  return {
    code,
    base64,
    rawPdf,
    blob: null,
    downloadUrl,
    previewUrl,
    filename: data?.filename || data?.file_name || data?.name || 'ТКП.pdf',
  };
}

function saveBlob(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = filename || 'ТКП.pdf';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

function pdfBlobFromBase64(value) {
  const binary = atob(normalizeBase64(value));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Blob([bytes], { type: 'application/pdf' });
}

function pdfBlobFromRaw(value) {
  let raw = decodeMaybeUrlEncoded(value);
  const pdfIndex = raw.indexOf('%PDF');
  if (pdfIndex > 0) {
    raw = raw.slice(pdfIndex);
  }
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) {
    bytes[i] = raw.charCodeAt(i) & 0xff;
  }
  return new Blob([bytes], { type: 'application/pdf' });
}

async function downloadTkpPdf(pdf) {
  const filename = pdf?.filename || 'ТКП.pdf';
  if (pdf?.blob) {
    saveBlob(pdf.blob, filename);
    return;
  }
  if (pdf?.base64) {
    saveBlob(pdfBlobFromBase64(pdf.base64), filename);
    return;
  }
  if (pdf?.rawPdf) {
    saveBlob(pdfBlobFromRaw(pdf.rawPdf), filename);
    return;
  }
  if (pdf?.downloadUrl) {
    const response = await fetch(pdf.downloadUrl);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    saveBlob(await response.blob(), filename);
  }
}

function buildTkpPdfBody(quote, accessories) {
  if (!quote?.equipmentId || !quote?.equipmentName) return null;
  return {
    equipment_name: quote.equipmentName,
    equipment_id: quote.equipmentId,
    price: quote.priceRub ?? parsePriceRub(quote.priceDisplay),
    phone: TKP_MOCK_PHONE,
    email: TKP_MOCK_EMAIL,
    accessories: (accessories || []).map((item) => ({
      name: item.name,
      desc: item.desc,
      price: item.price,
    })),
  };
}

function TkpPdfCard({ pdf }) {
  if (!pdf) return null;
  const handleDownload = async () => {
    try {
      await downloadTkpPdf(pdf);
    } catch (error) {
      console.error('[tkp-pdf-download] ошибка:', error);
      window.alert('Не удалось скачать PDF-файл. Попробуйте сформировать ТКП ещё раз.');
    }
  };

  return (
    <div className="chat-widget__pdf-card">
      <div className="chat-widget__pdf-preview-box">
        {pdf.previewUrl ? (
          <img src={pdf.previewUrl} alt={pdf.filename || 'PDF ТКП'} />
        ) : (
          <div className="chat-widget__pdf-placeholder">
            <span className="chat-widget__pdf-label">PDF</span>
          </div>
        )}
        {(pdf.blob || pdf.base64 || pdf.rawPdf || pdf.downloadUrl) && (
          <button
            type="button"
            className="chat-widget__pdf-download"
            onClick={handleDownload}
            title="Скачать ТКП"
          >
            <span aria-hidden="true">↓</span>
          </button>
        )}
      </div>
      <div className="chat-widget__pdf-name">{pdf.filename || 'ТКП.pdf'}</div>
    </div>
  );
}

function AccessoriesSelector({ items, selectedIds, onToggle }) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const selectedSet = new Set(selectedIds || []);

  return (
    <div className="chat-widget__accessories">
      <div className="chat-widget__accessories-title">Выберите аксессуары для точного расчёта:</div>
      <div className="chat-widget__accessories-list">
        {items.map((item) => {
          const isSelected = selectedSet.has(item.id);
          return (
            <button
              type="button"
              key={item.id}
              className={`chat-widget__accessory ${isSelected ? 'chat-widget__accessory--selected' : ''}`}
              onClick={() => onToggle(item, items)}
              title={item.desc || item.name}
            >
              <span className="chat-widget__accessory-name">{item.name}</span>
              {item.price != null && (
                <span className="chat-widget__accessory-price">
                  {Number(item.price).toLocaleString('ru-RU')} ₽
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function EquipmentShowcase({ items, onPick, onCurrentItemChange }) {
  const [idx, setIdx] = useState(0);
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    setImageFailed(false);
  }, [idx, items]);

  useEffect(() => {
    if (typeof onCurrentItemChange !== 'function') return;
    const item = Array.isArray(items) && items.length ? items[idx] || {} : {};
    onCurrentItemChange(item);
  }, [idx, items, onCurrentItemChange]);

  if (!Array.isArray(items) || items.length === 0) return null;
  const n = items.length;
  const item = items[idx] || {};
  const single = n === 1;
  const src = resolveEquipmentImageUrl(item.image);
  const label = (item.model || item.name || '').trim() || '—';

  const handleSelectCurrent = () => {
    if (typeof onPick !== 'function' || !item || Object.keys(item).length === 0) return;
    onPick({ ...item });
  };

  return (
    <div className="chat-widget__equipment">
      {!single && (
        <div className="chat-widget__equipment-toolbar" aria-label="Слайдер приборов">
          <button
            type="button"
            className="chat-widget__eq-nav"
            disabled={idx <= 0}
            onClick={() => setIdx((i) => Math.max(0, i - 1))}
            aria-label="Предыдущий"
          >
            ‹
          </button>
          <span className="chat-widget__eq-counter">
            {idx + 1} / {n}
          </span>
          <button
            type="button"
            className="chat-widget__eq-nav"
            disabled={idx >= n - 1}
            onClick={() => setIdx((i) => Math.min(n - 1, i + 1))}
            aria-label="Следующий"
          >
            ›
          </button>
        </div>
      )}
      <div
        className="chat-widget__equipment-card chat-widget__equipment-card--selectable"
        role="button"
        tabIndex={0}
        onClick={handleSelectCurrent}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleSelectCurrent();
          }
        }}
        aria-label={`Выбрать: ${label}`}
      >
        {src && !imageFailed ? (
          <img
            className="chat-widget__equipment-img"
            src={src}
            alt={label}
            onError={() => {
              if (process.env.NODE_ENV === 'development') {
                // eslint-disable-next-line no-console
                console.warn('[equipment image] load failed, tried:', src, 'raw:', item?.image);
              }
              setImageFailed(true);
            }}
          />
        ) : null}
        {(!src || imageFailed) && (
          <div className="chat-widget__equipment-placeholder">
            {imageFailed
              ? 'Превью не загрузилось (проверьте путь к файлу на сервисе 8001).'
              : 'Нет изображения'}
            {imageFailed && src && (
              <div className="chat-widget__equipment-url-hint" title={src}>
                {src.length > 48 ? `${src.slice(0, 46)}…` : src}
              </div>
            )}
          </div>
        )}
        <div className="chat-widget__equipment-model">{label}</div>
        {item.name && item.name !== item.model && (item.name || '').trim() && (
          <div className="chat-widget__equipment-name">{item.name}</div>
        )}
      </div>
    </div>
  );
}

export function ChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [chatId, setChatId] = useState(null);
  const hasMessages = useRef(false);
  const fileInputRef = useRef(null);

  const [selectedImage, setSelectedImage] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [selectedPdf, setSelectedPdf] = useState(null);

  const [hintState, setHintState] = useState({
    currentState: 'start',
    hints: [],
    showBack: false,
    isFinal: false,
    expectsInput: false,
  });
  const [hintLocked, setHintLocked] = useState(false);

  const isOrderPdfStep = hintState.currentState === 'order_pdf_request';

  /** Пока показан слайдер оборудования — ждём выбор, подсказки (как в order_final) не показываем. */
  const [awaitingEquipmentSelection, setAwaitingEquipmentSelection] = useState(false);
  /** Текущая карточка на слайдере (для «Получить цену»). */
  const sliderEquipmentRef = useRef(null);
  /** Спецификация из PDF (для расчёта цены на :8010), заполняется при ответе 1С. */
  const lastOrderSpecsRef = useRef(null);
  const [showExactCostHint, setShowExactCostHint] = useState(false);
  const [showTkpPdfHint, setShowTkpPdfHint] = useState(false);
  const exactCostBodyRef = useRef(null);
  const estimateQuoteRef = useRef(null);
  const selectedAccessoriesRef = useRef([]);
  const [selectedAccessoryIds, setSelectedAccessoryIds] = useState([]);

  const pickEquipmentToInput = useCallback((raw) => {
    if (typeof console.clear === 'function') {
      console.clear();
    }
    if (raw && typeof raw === 'object') {
      console.log({ ...raw });
    } else {
      console.log(raw);
    }
    const line = (raw?.model || raw?.name || '').toString().trim();
    if (line) {
      setInputValue(line);
    }
  }, []);

  const chatIdRef = useRef(null);
  const chatCreatePromiseRef = useRef(null);

  useEffect(() => {
    chatIdRef.current = chatId;
  }, [chatId]);

  /** Чат в БД создаётся при первом сообщении/подсказке (не при F5), чтобы не дублировать POST и не ловить 500 до действия пользователя. */
  const ensureChatId = useCallback(async () => {
    if (chatIdRef.current != null) return chatIdRef.current;
    if (!chatCreatePromiseRef.current) {
      chatCreatePromiseRef.current = createChat({ title: 'Новый чат' })
        .then((res) => {
          const id = res.data.id;
          chatIdRef.current = id;
          setChatId(id);
          return id;
        })
        .finally(() => {
          chatCreatePromiseRef.current = null;
        });
    }
    return chatCreatePromiseRef.current;
  }, []);

  const initializeChat = useCallback(async () => {
    hasMessages.current = false;
    setChatId(null);
    chatIdRef.current = null;
    chatCreatePromiseRef.current = null;

    try {
      const hintsResponse = await getHints('start');
      const hintsData = hintsResponse.data;

      setHintState({
        currentState: hintsData.current_state,
        hints: hintsData.hints || [],
        showBack: hintsData.show_back,
        isFinal: hintsData.is_final,
        expectsInput: hintsData.expects_input,
      });

      setMessages([
        {
          id: 1,
          from: 'bot',
          text: hintsData.bot_message || 'Здравствуйте! Чем я могу Вам помочь?',
          time: new Date(),
        },
      ]);

      setHintLocked(false);
      setAwaitingEquipmentSelection(false);
      sliderEquipmentRef.current = null;
      lastOrderSpecsRef.current = null;
      exactCostBodyRef.current = null;
      estimateQuoteRef.current = null;
      selectedAccessoriesRef.current = [];
      setShowExactCostHint(false);
      setShowTkpPdfHint(false);
      setSelectedAccessoryIds([]);
    } catch (error) {
      console.error('Error initializing chat (hints API):', error);
      const h = FALLBACK_HINTS_START;
      setHintState({
        currentState: h.current_state,
        hints: h.hints || [],
        showBack: h.show_back,
        isFinal: h.is_final,
        expectsInput: h.expects_input,
      });
      setMessages([
        {
          id: 1,
          from: 'bot',
          text: h.bot_message,
          time: new Date(),
        },
      ]);
      setHintLocked(false);
      setAwaitingEquipmentSelection(false);
      sliderEquipmentRef.current = null;
      lastOrderSpecsRef.current = null;
      exactCostBodyRef.current = null;
      estimateQuoteRef.current = null;
      selectedAccessoriesRef.current = [];
      setShowExactCostHint(false);
      setShowTkpPdfHint(false);
      setSelectedAccessoryIds([]);
    }
  }, []);

  useEffect(() => {
    initializeChat();
  }, [initializeChat]);

  useEffect(() => {
    const handleBeforeUnload = () => {
      if (chatId) {
        const base = API_BASE_URL.endsWith('/') ? API_BASE_URL.slice(0, -1) : API_BASE_URL;
        const url = `${base}/chats/${chatId}/finalize/`;
        navigator.sendBeacon(url, JSON.stringify({}));
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden' && chatId && hasMessages.current) {
        finalizeChat(chatId).catch(console.error);
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      document.removeEventListener('visibilitychange', handleVisibilityChange);

      if (chatId && hasMessages.current) {
        finalizeChat(chatId).catch(console.error);
      }
    };
  }, [chatId]);

  const toggleOpen = () => {
    setIsOpen((prev) => !prev);
  };

  const handleHintSelect = async (hint) => {
    const userMessage = {
      id: Date.now(),
      from: 'user',
      text: hint.text,
      time: new Date(),
      isHint: true,
    };
    setMessages((prev) => [...prev, userMessage]);

    hasMessages.current = true;
    setIsTyping(true);

    try {
      const id = await ensureChatId();
      const response = await createMessage(id, {
        content: hint.text,
        hint_state: hintState.currentState,
        is_hint_selection: true,
        hint_locked: hintLocked,
      });
      setAwaitingEquipmentSelection(false);

      if (response.data.hint_state) {
        const newState = response.data.hint_state;
        setHintState({
          currentState: newState.current_state,
          hints: newState.hints || [],
          showBack: newState.show_back,
          isFinal: newState.is_final,
          expectsInput: newState.expects_input,
        });

        if (newState.is_final) {
          setHintLocked(false);
        } else {
          setHintLocked(true);
        }
      } else {
        setHintLocked(true);
      }

      if (isOrderFinalWithSpecs(response.data)) {
        const specs = response.data.order_specs_json;
        try {
          const res = await postEquipmentSpecsTo1c(specs);
          const d = res.data;
          if (d?.status === 'success' && Array.isArray(d?.equipment) && d.equipment.length > 0) {
            lastOrderSpecsRef.current = specs;
            setMessages((prev) => [
              ...prev,
              {
                id: `eq-hint-${Date.now()}`,
                from: 'bot',
                kind: 'equipment',
                equipment: d.equipment,
                time: new Date(),
              },
            ]);
            setAwaitingEquipmentSelection(true);
          } else {
            setMessages((prev) => [
              ...prev,
              {
                id: Date.now(),
                from: 'bot',
                text: d?.message || 'Данные приняты, список оборудования пуст.',
                time: new Date(),
              },
            ]);
          }
        } catch (err) {
          console.error('[1C] ошибка:', err);
          const msg =
            err?.response?.data?.message ||
            (typeof err?.response?.data === 'string' ? err.response.data : null) ||
            err?.message ||
            'Ошибка сети';
          setMessages((prev) => [
            ...prev,
            {
              id: Date.now(),
              from: 'bot',
              text: `Не удалось получить подбор оборудования: ${msg}`,
              time: new Date(),
            },
          ]);
        }
      } else {
        const botMessages = response.data.messages?.filter((msg) => !msg.is_user) || [];
        if (botMessages.length > 0) {
          const t = (botMessages[0].content || '').trim();
          if (t) {
            const botMsg = {
              id: botMessages[0].id,
              from: 'bot',
              text: botMessages[0].content || 'Пустой ответ сервера.',
              time: new Date(botMessages[0].created_at),
            };
            setMessages((prev) => [...prev, botMsg]);
          }
        }
      }
      logIfVerificationPassed(response.data);
    } catch (error) {
      console.error('Error selecting hint:', error);
      const errorMsg = {
        id: Date.now() + 1,
        from: 'bot',
        text: 'Извините, произошла ошибка. Попробуйте позже.',
        time: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleGetPriceHint = async () => {
    const eq = sliderEquipmentRef.current;
    const label = (eq?.model || eq?.name || '').toString().trim();
    if (!label) {
      window.alert('Пролистайте слайдер и выберите прибор, затем нажмите «Получить цену».');
      return;
    }
    const userMessage = {
      id: Date.now(),
      from: 'user',
      text: 'Получить цену',
      time: new Date(),
      isHint: true,
    };
    setMessages((prev) => [...prev, userMessage]);
    hasMessages.current = true;
    setIsTyping(true);
    try {
      const id = await ensureChatId();
      const specsForPrice = lastOrderSpecsRef.current || {};
      const estimateBody = buildEstimatePriceBody(eq, specsForPrice);
      const estimatePromise = estimateBody ? postEstimatePrice(estimateBody) : null;
      const response = await createMessage(id, {
        content: 'Получить цену',
        hint_state: hintState.currentState,
        is_hint_selection: true,
        hint_locked: hintLocked,
        equipment_for_price: {
          id: eq?.id ?? eq?.equipment_id ?? '',
          model: eq?.model ?? '',
          name: eq?.name ?? '',
          image: eq?.image ?? '',
        },
        order_specs_for_price: specsForPrice,
      });
      setAwaitingEquipmentSelection(false);

      if (response.data.hint_state) {
        const newState = response.data.hint_state;
        setHintState({
          currentState: newState.current_state,
          hints: newState.hints || [],
          showBack: newState.show_back,
          isFinal: newState.is_final,
          expectsInput: newState.expects_input,
        });
        if (newState.is_final) {
          setHintLocked(false);
        } else {
          setHintLocked(true);
        }
      } else {
        setHintLocked(true);
      }

      const botMessages = response.data.messages?.filter((msg) => !msg.is_user) || [];
      if (botMessages.length > 0) {
        const t = (botMessages[0].content || '').trim();
        if (t) {
          const botMsg = {
            id: botMessages[0].id,
            from: 'bot',
            text: botMessages[0].content || 'Пустой ответ сервера.',
            time: new Date(botMessages[0].created_at),
          };
          setMessages((prev) => [...prev, botMsg]);
        }
      }
      if (estimatePromise) {
        try {
          const estimateResponse = await estimatePromise;
          const estimateData = estimateResponse.data || {};
          const equipmentName = (estimateData.equipment_name || estimateBody.equipment.name || label).trim();
          const equipmentId = (estimateData.equipment_id || estimateBody.equipment.id || '').toString().trim();
          const priceRub = parsePriceRub(estimateData.price_rub ?? estimateData.price ?? estimateData.price_display);
          const priceDisplay = (estimateData.price_display || '').trim();
          const text = priceDisplay
            ? `Примерная цена на выбранное оборудование «${equipmentName}»: ${priceDisplay}.`
            : 'Расчёт цены выполнен, но сервис не вернул отображаемую стоимость.';
          setMessages((prev) => [
            ...prev,
            {
              id: `estimate-${Date.now()}`,
              from: 'bot',
              text,
              time: new Date(),
            },
          ]);
          exactCostBodyRef.current = buildTkpAccessoriesBody(estimateBody);
          estimateQuoteRef.current = {
            equipmentName,
            equipmentId,
            priceRub,
            priceDisplay,
          };
          selectedAccessoriesRef.current = [];
          setShowExactCostHint(Boolean(exactCostBodyRef.current));
          setShowTkpPdfHint(false);
          setSelectedAccessoryIds([]);
        } catch (estimateError) {
          console.error('[estimate-price] ошибка:', estimateError);
          exactCostBodyRef.current = null;
          estimateQuoteRef.current = null;
          selectedAccessoriesRef.current = [];
          setShowExactCostHint(false);
          setShowTkpPdfHint(false);
          const msg =
            estimateError?.response?.data?.message ||
            estimateError?.response?.data?.error ||
            estimateError?.message ||
            'Ошибка сети';
          setMessages((prev) => [
            ...prev,
            {
              id: `estimate-error-${Date.now()}`,
              from: 'bot',
              text: `Автоматический расчёт цены недоступен: ${msg}. Точную стоимость уточнит менеджер.`,
              time: new Date(),
            },
          ]);
        }
      } else {
        exactCostBodyRef.current = null;
        estimateQuoteRef.current = null;
        selectedAccessoriesRef.current = [];
        setShowExactCostHint(false);
        setShowTkpPdfHint(false);
        setMessages((prev) => [
          ...prev,
          {
            id: `estimate-missing-${Date.now()}`,
            from: 'bot',
            text:
              'Ориентировочный расчёт не выполнен: не хватает кода прибора или параметров из итоговой спецификации.',
            time: new Date(),
          },
        ]);
      }
      logIfVerificationPassed(response.data);
    } catch (error) {
      console.error('Error get price hint:', error);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          from: 'bot',
          text: 'Извините, произошла ошибка. Попробуйте позже.',
          time: new Date(),
        },
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  const logSelectedAccessories = useCallback((ids, items) => {
    const selected = (items || []).filter((item) => ids.includes(item.id)).map((item) => ({ ...item }));
    if (typeof console.clear === 'function') {
      console.clear();
    }
    console.log(selected);
    return selected;
  }, []);

  const handleAccessoryToggle = useCallback(
    (item, items) => {
      setSelectedAccessoryIds((prev) => {
        const exists = prev.includes(item.id);
        const next = exists ? prev.filter((id) => id !== item.id) : [...prev, item.id];
        const selected = logSelectedAccessories(next, items);
        selectedAccessoriesRef.current = selected;
        setShowTkpPdfHint(selected.length > 0);
        return next;
      });
    },
    [logSelectedAccessories]
  );

  const handleExactCostHint = async () => {
    const body = exactCostBodyRef.current;
    const userMessage = {
      id: Date.now(),
      from: 'user',
      text: 'Рассчитать точную стоимость',
      time: new Date(),
      isHint: true,
    };
    setMessages((prev) => [...prev, userMessage]);
    if (!body) {
      setMessages((prev) => [
        ...prev,
        {
          id: `tkp-missing-${Date.now()}`,
          from: 'bot',
          text: 'Не удалось рассчитать точную стоимость: нет данных выбранного оборудования или спецификации.',
          time: new Date(),
        },
      ]);
      return;
    }

    setIsTyping(true);
    try {
      const response = await postTkpAccessories(body);
      const accessories = Array.isArray(response.data?.accessories) ? response.data.accessories : [];
      setShowExactCostHint(false);
      setShowTkpPdfHint(false);
      selectedAccessoriesRef.current = [];
      setSelectedAccessoryIds([]);
      setMessages((prev) => [
        ...prev,
        {
          id: `accessories-${Date.now()}`,
          from: 'bot',
          kind: 'accessories',
          accessories,
          time: new Date(),
        },
      ]);
      logSelectedAccessories([], accessories);
    } catch (error) {
      console.error('[tkp-accessories] ошибка:', error);
      const msg =
        error?.response?.data?.message ||
        error?.response?.data?.error ||
        error?.message ||
        'Ошибка сети';
      setMessages((prev) => [
        ...prev,
        {
          id: `tkp-error-${Date.now()}`,
          from: 'bot',
          text: `Не удалось получить список аксессуаров: ${msg}`,
          time: new Date(),
        },
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleTkpPdfHint = async () => {
    const selectedAccessories = selectedAccessoriesRef.current || [];
    const body = buildTkpPdfBody(estimateQuoteRef.current, selectedAccessories);
    const userMessage = {
      id: Date.now(),
      from: 'user',
      text: 'Получить ТКП',
      time: new Date(),
      isHint: true,
    };
    setMessages((prev) => [...prev, userMessage]);

    if (!body || selectedAccessories.length === 0) {
      setMessages((prev) => [
        ...prev,
        {
          id: `tkp-pdf-missing-${Date.now()}`,
          from: 'bot',
          text: 'Не удалось сформировать ТКП: выберите аксессуары и дождитесь расчёта примерной цены.',
          time: new Date(),
        },
      ]);
      setShowTkpPdfHint(false);
      return;
    }

    setIsTyping(true);
    try {
      const response = await postTkpPdf(body);
      const pdf = buildTkpPdfCard(response.data || {}, response.headers || {});
      setShowTkpPdfHint(false);
      setMessages((prev) => [
        ...prev,
        {
          id: `tkp-pdf-${Date.now()}`,
          from: 'bot',
          kind: 'tkpPdf',
          text: 'ТКП сформировано. Его можно скачать по карточке ниже.',
          pdf,
          time: new Date(),
        },
      ]);
    } catch (error) {
      console.error('[tkp-pdf] ошибка:', error);
      const msg =
        error?.response?.data?.message ||
        error?.response?.data?.error ||
        error?.message ||
        'Ошибка сети';
      setMessages((prev) => [
        ...prev,
        {
          id: `tkp-pdf-error-${Date.now()}`,
          from: 'bot',
          text: `Не удалось сформировать PDF ТКП: ${msg}`,
          time: new Date(),
        },
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleBack = async () => {
    try {
      const response = await transitionHints({
        current_state: hintState.currentState,
        action: 'back',
      });

      const newState = response.data.current_state;

      setHintState({
        currentState: newState,
        hints: response.data.hints || [],
        showBack: response.data.show_back,
        isFinal: response.data.is_final,
        expectsInput: response.data.expects_input,
      });

      if (newState === 'start') {
        setHintLocked(false);
      }

      if (response.data.bot_message) {
        const botMsg = {
          id: Date.now(),
          from: 'bot',
          text: response.data.bot_message,
          time: new Date(),
        };
        setMessages((prev) => [...prev, botMsg]);
      }
    } catch (error) {
      console.error('Error going back:', error);
    }
  };

  const addMessage = async (text, from = 'user', image = null, pdf = null) => {
    if (!text.trim() && !image && !pdf) return;

    const newMessage = {
      id: Date.now(),
      from,
      text: text.trim(),
      time: new Date(),
      imagePreview: image ? URL.createObjectURL(image) : null,
      pdfName: pdf ? pdf.name : null,
    };

    setMessages((prev) => [...prev, newMessage]);

    if (from === 'user') {
      hasMessages.current = true;
      setIsTyping(true);
      try {
        const id = await ensureChatId();
        const response = await createMessage(
          id,
          {
            content: text.trim(),
            hint_state: hintState.currentState,
            is_hint_selection: false,
            hint_locked: hintLocked,
          },
          image,
          pdf
        );
        setAwaitingEquipmentSelection(false);

        if (response.data.messages) {
          const userMsg = response.data.messages.find((msg) => msg.is_user);
          if (userMsg) {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === newMessage.id
                  ? {
                      ...msg,
                      ...(userMsg.image_url ? { imageUrl: userMsg.image_url } : {}),
                      ...(userMsg.attachment_url ? { attachmentUrl: userMsg.attachment_url } : {}),
                    }
                  : msg
              )
            );
          }
        }

        if (response.data.hint_state) {
          const newState = response.data.hint_state;
          setHintState({
            currentState: newState.current_state,
            hints: newState.hints || [],
            showBack: newState.show_back,
            isFinal: newState.is_final,
            expectsInput: newState.expects_input,
          });

          if (newState.current_state === 'start' || newState.is_final) {
            setHintLocked(false);
          } else if (newState.hint_locked !== undefined) {
            setHintLocked(newState.hint_locked);
          }
        }

        if (isOrderFinalWithSpecs(response.data)) {
          const specs = response.data.order_specs_json;
          try {
            const res = await postEquipmentSpecsTo1c(specs);
            const d = res.data;
            if (d?.status === 'success' && Array.isArray(d?.equipment) && d.equipment.length > 0) {
              lastOrderSpecsRef.current = specs;
              setMessages((prev) => [
                ...prev,
                {
                  id: `eq-${Date.now()}`,
                  from: 'bot',
                  kind: 'equipment',
                  equipment: d.equipment,
                  time: new Date(),
                },
              ]);
              setAwaitingEquipmentSelection(true);
            } else {
              setMessages((prev) => [
                ...prev,
                {
                  id: Date.now(),
                  from: 'bot',
                  text: d?.message || 'Данные приняты, список оборудования пуст.',
                  time: new Date(),
                },
              ]);
            }
          } catch (err) {
            console.error('[1C] ошибка:', err);
            const msg =
              err?.response?.data?.message ||
              (typeof err?.response?.data === 'string' ? err.response.data : null) ||
              err?.message ||
              'Ошибка сети';
            setMessages((prev) => [
              ...prev,
              {
                id: Date.now(),
                from: 'bot',
                text: `Не удалось получить подбор оборудования: ${msg}`,
                time: new Date(),
              },
            ]);
          }
        } else {
          const botMessages = response.data.messages?.filter((msg) => !msg.is_user) || [];
          if (botMessages.length > 0) {
            const t = (botMessages[0].content || '').trim();
            if (t) {
              const botMsg = {
                id: botMessages[0].id,
                from: 'bot',
                text: botMessages[0].content || 'Пустой ответ сервера.',
                time: new Date(botMessages[0].created_at),
              };
              setMessages((prev) => [...prev, botMsg]);
            }
          }
        }
        logIfVerificationPassed(response.data);
      } catch (error) {
        console.error('Error saving message:', error);
        const errorMsg = {
          id: Date.now() + 1,
          from: 'bot',
          text: 'Извините, произошла ошибка. Попробуйте позже.',
          time: new Date(),
        };
        setMessages((prev) => [...prev, errorMsg]);
      } finally {
        setIsTyping(false);
      }
    }
  };

  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (isOrderPdfStep) {
      const ok = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
      if (!ok) {
        alert('Пожалуйста, выберите файл в формате PDF');
        return;
      }
      if (file.size > 15 * 1024 * 1024) {
        alert('Размер PDF не должен превышать 15 МБ');
        return;
      }
      setSelectedPdf(file);
      setSelectedImage(null);
      setImagePreview(null);
    } else {
      if (!file.type.startsWith('image/')) {
        alert('Пожалуйста, выберите изображение');
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        alert('Размер файла не должен превышать 5MB');
        return;
      }
      setSelectedImage(file);
      setImagePreview(URL.createObjectURL(file));
      setSelectedPdf(null);
    }
  };

  const handleRemoveAttachment = () => {
    setSelectedImage(null);
    setImagePreview(null);
    setSelectedPdf(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleSend = () => {
    if (!inputValue.trim() && !selectedImage && !selectedPdf) return;
    addMessage(inputValue, 'user', selectedImage, selectedPdf);
    setSelectedImage(null);
    setImagePreview(null);
    setSelectedPdf(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    setInputValue('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  useEffect(() => {
    const container = document.querySelector('.chat-widget__messages');
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }, [messages, isOpen, isTyping]);

  return (
    <div className="chat-widget">
      <button
        type="button"
        className={`chat-widget__toggle ${isOpen ? 'chat-widget__toggle--open' : ''}`}
        onClick={toggleOpen}
        aria-label="Открыть чат"
      />

      <div className={`chat-widget__window ${isOpen ? 'chat-widget__window--visible' : ''}`}>
        <header className="chat-widget__header">
          <div className="chat-widget__header-info">
            <div className="chat-widget__avatar" />
            <div>
              <div className="chat-widget__title">Turbo-don чат</div>
              <div className="chat-widget__subtitle">Онлайн • обычно отвечает за пару секунд</div>
            </div>
          </div>
          <button type="button" className="chat-widget__close" onClick={toggleOpen} aria-label="Закрыть чат">
            ×
          </button>
        </header>

        <div className="chat-widget__messages">
          {messages.map((message) => (
            <div
              key={message.id}
              className={`chat-widget__message chat-widget__message--${message.from}`}
            >
              <div className="chat-widget__bubble">
                {message.kind === 'equipment' && message.equipment?.length ? (
                  <EquipmentShowcase
                    items={message.equipment}
                    onPick={pickEquipmentToInput}
                    onCurrentItemChange={(item) => {
                      sliderEquipmentRef.current = item;
                    }}
                  />
                ) : message.kind === 'accessories' && message.accessories?.length ? (
                  <AccessoriesSelector
                    items={message.accessories}
                    selectedIds={selectedAccessoryIds}
                    onToggle={handleAccessoryToggle}
                  />
                ) : message.kind === 'tkpPdf' ? (
                  <>
                    {message.text && <span>{message.text}</span>}
                    <TkpPdfCard pdf={message.pdf} />
                  </>
                ) : (
                  <>
                {message.text && <span>{message.text}</span>}
                {(message.imageUrl || message.imagePreview) && (
                  <div className="chat-widget__image">
                    <img
                      src={message.imageUrl || message.imagePreview}
                      alt="Прикреплённое фото"
                      onClick={() => window.open(message.imageUrl || message.imagePreview, '_blank')}
                    />
                  </div>
                )}
                {(message.attachmentUrl || message.pdfName) && (
                  <div className="chat-widget__attachment">
                    <a
                      href={message.attachmentUrl || '#'}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(ev) => {
                        if (!message.attachmentUrl) ev.preventDefault();
                      }}
                    >
                      📎 {message.pdfName || 'PDF-файл'}
                    </a>
                  </div>
                )}
                  </>
                )}
              </div>
              <div className="chat-widget__meta">
                <span className="chat-widget__time">{formatTime(message.time)}</span>
              </div>
            </div>
          ))}

          {isTyping && (
            <div className="chat-widget__message chat-widget__message--bot">
              <div className="chat-widget__bubble chat-widget__bubble--typing">
                <span className="typing-dots">
                  <span />
                  <span />
                  <span />
                </span>
              </div>
              <div className="chat-widget__meta">
                <span className="chat-widget__time">печатает...</span>
              </div>
            </div>
          )}

        </div>

        <div className="chat-widget__footer">
          {awaitingEquipmentSelection && (
            <div className="chat-widget__hints">
              <button type="button" className="chat-widget__hint" onClick={handleGetPriceHint}>
                Получить цену
              </button>
            </div>
          )}
          {showExactCostHint && !awaitingEquipmentSelection && (
            <div className="chat-widget__hints">
              <button type="button" className="chat-widget__hint" onClick={handleExactCostHint}>
                Рассчитать точную стоимость
              </button>
            </div>
          )}
          {showTkpPdfHint && !awaitingEquipmentSelection && !showExactCostHint && (
            <div className="chat-widget__hints">
              <button type="button" className="chat-widget__hint" onClick={handleTkpPdfHint}>
                Получить ТКП
              </button>
            </div>
          )}
          {hintState.hints && hintState.hints.length > 0 && !awaitingEquipmentSelection && !showExactCostHint && !showTkpPdfHint && (
            <div className="chat-widget__hints">
              {hintState.showBack && (
                <button type="button" className="chat-widget__hint chat-widget__hint--back" onClick={handleBack}>
                  ← Вернуться
                </button>
              )}
              {hintState.hints.map((hint, index) => (
                <button
                  type="button"
                  key={index}
                  className="chat-widget__hint"
                  onClick={() => handleHintSelect(hint)}
                >
                  {hint.text}
                </button>
              ))}
            </div>
          )}

          {hintState.showBack && (!hintState.hints || hintState.hints.length === 0) && !hintState.isFinal && !awaitingEquipmentSelection && !showExactCostHint && !showTkpPdfHint && (
            <div className="chat-widget__hints">
              <button type="button" className="chat-widget__hint chat-widget__hint--back" onClick={handleBack}>
                ← Вернуться
              </button>
            </div>
          )}

          {imagePreview && (
            <div className="chat-widget__image-preview">
              <img src={imagePreview} alt="Превью" />
              <button
                type="button"
                className="chat-widget__image-remove"
                onClick={handleRemoveAttachment}
                title="Удалить вложение"
              >
                ×
              </button>
            </div>
          )}
          {selectedPdf && !imagePreview && (
            <div className="chat-widget__pdf-preview">
              <span>📎 {selectedPdf.name}</span>
              <button type="button" className="chat-widget__image-remove" onClick={handleRemoveAttachment} title="Удалить PDF">
                ×
              </button>
            </div>
          )}

          <div className="chat-widget__input-row">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileSelect}
              accept={isOrderPdfStep ? '.pdf,application/pdf' : 'image/*'}
              style={{ display: 'none' }}
            />

            <button
              type="button"
              className="chat-widget__attach-btn"
              onClick={() => fileInputRef.current?.click()}
              title={isOrderPdfStep ? 'Прикрепить PDF' : 'Прикрепить фото'}
            >
              📎
            </button>

            <textarea
              className="chat-widget__input"
              rows={1}
              placeholder={
                awaitingEquipmentSelection
                  ? 'Нажмите на карточку прибора или введите сообщение...'
                  : isOrderPdfStep
                    ? 'Прикрепите PDF со спецификацией (при желании дополните текстом)...'
                    : hintState.expectsInput
                      ? 'Введите информацию...'
                      : 'Напишите сообщение...'
              }
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
            />
            <button
              type="button"
              className="chat-widget__send-btn"
              onClick={handleSend}
              disabled={!inputValue.trim() && !selectedImage && !selectedPdf}
            >
              ➤
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
