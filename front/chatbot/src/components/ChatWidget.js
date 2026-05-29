import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import {
  createChat,
  createMessage,
  finalizeChat,
  getHints,
  fetchSearchEquipment,
  postEstimatePrice,
  postTkpAccessories,
  postTkpPdf,
  transitionHints,
} from '../api';
import {
  API_BASE_URL,
  getEquipmentImageCandidateUrlsFromItem,
  getSubmitHouseholdGasRequestUrl,
  getSubmitSpuApplicationUrl,
  LIQUID_TZ_QUESTIONNAIRE_URL,
  TKP_PDF_URL,
} from '../config';
import { FALLBACK_HINTS_START } from '../data/fallbackHintsStart';
import { formatTime } from '../utils/formatTime';
import {
  GasSpuResultCard,
  GasSpuReviewBlock,
} from './gasSpuResultCard';
import {
  OrderSpecsConfirmTable,
  enrichBotMessage,
  shouldShowOrderSpecsBotMessage,
} from './orderSpecsConfirmTable';
import { OrderSpecsTextClarify } from './OrderSpecsTextClarify';
import { getBundledEquipmentImageUrls } from '../assets/equipmentImages';
import { GrandGasMetersPriceBlock } from './GrandGasMetersPriceBlock';
import { normalizeSpecs } from '../utils/searchEquipment';

/** Консоль браузера: фактический POST на :8010 выполняет Django; здесь URL/тело совпадают с серверным запросом. */
/** Текст подсказки и кнопки на карточке СПУ — синхронно с backend (gas_spu_wizard.GAS_SPU_LEAVE_REQUEST). */
const GAS_SPU_LEAVE_REQUEST = 'Оставить заявку →';

/** Авто-рост поля ввода: одна строка по умолчанию, до ~5 строк, дальше прокрутка. */
const INPUT_MIN_HEIGHT_PX = 34;
const INPUT_MAX_HEIGHT_PX = 120;

/** Консоль: POST заявки СПУ на 1С выполняется в Django — URL и тело соответствуют серверу. */
function logSubmitSpuApplicationResponse(apiResponse) {
  if (!apiResponse?.data?.submit_spu_application) return;
  const lead = apiResponse.data.gas_spu_application_lead;
  const sel = apiResponse.data.gas_spu_selection;
  const request = apiResponse.data.submit_spu_application?._request;
  const email = (lead?.email || '').trim();
  const phone = (lead?.phone || '').trim();
  const requestBody = request?.body || {
    fullname: lead?.full_name || '',
    contact: email || phone,
    comment: lead?.tz_comments || '',
    source: 'my-bot',
    selection: sel?._last_payload || sel || {},
  };
  const method = request?.method || 'POST';
  const url = request?.url || getSubmitSpuApplicationUrl();
  const response = apiResponse.data.submit_spu_application;
  // eslint-disable-next-line no-console
  console.log('[submit-spu-application → 8010] method:', method);
  // eslint-disable-next-line no-console
  console.log('[submit-spu-application → 8010] url:', url);
  // eslint-disable-next-line no-console
  console.log('[submit-spu-application → 8010] body:', JSON.stringify(requestBody, null, 2));
  // eslint-disable-next-line no-console
  console.log('[submit-spu-application → 8010] response:', JSON.stringify(response, null, 2));
}

function logSubmitHouseholdGasResponse(apiResponse) {
  if (!apiResponse?.data?.submit_household_gas) return;
  const lead = apiResponse.data.household_gas_lead;
  const email = (lead?.email || '').trim();
  const phone = (lead?.phone || '').trim();
  const requestBody = lead
    ? {
        fullname: lead.full_name || '',
        contact: email || phone,
        comment: lead.comment || '',
        organization: lead.organization || '',
        phone,
        email,
        source: 'external-bot',
        selected_items: Array.isArray(lead.selected_items) ? lead.selected_items : [],
      }
    : null;
  // eslint-disable-next-line no-console
  console.log('[submit-household-gas → 8010]', {
    method: 'POST',
    url: getSubmitHouseholdGasRequestUrl(),
    body: requestBody,
    response: apiResponse.data.submit_household_gas,
  });
}

function isOrderFinalWithSpecs(data) {
  return data?.hint_state?.current_state === 'order_final' && data?.order_specs_json != null;
}

/** Синхронизация hintState с ответом API (current_state → currentState). */
function applyHintStateFromResponse(data, setHintState, setHintLocked) {
  const hs = data?.hint_state;
  if (!hs) return;
  setHintState({
    currentState: hs.current_state,
    hints: hs.hints || [],
    showBack: hs.show_back,
    isFinal: hs.is_final,
    expectsInput: hs.expects_input,
    hintsOnly: hs.hints_only ?? false,
  });
  if (hs.current_state === 'start' || hs.is_final) {
    setHintLocked(false);
  } else if (hs.hint_locked !== undefined) {
    setHintLocked(hs.hint_locked);
  }
}

const LIQUID_TZ_MAX_BYTES = 10 * 1024 * 1024;
const LIQUID_TZ_EXTS = ['.pdf', '.doc', '.docx', '.txt', '.zip', '.rar'];

const ORDER_SPECS_MAX_BYTES = 15 * 1024 * 1024;
const ORDER_SPECS_EXTS = ['.pdf', '.docx'];
const ORDER_SPECS_ACCEPT =
  '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document';

/** Шаги сценария «Расходомеры» (кнопка «Назад» — на предыдущий шаг, не на главную). */
const FLOWMETER_HINT_STATES = new Set([
  'order_pdf_request',
  'order_specs_clarify',
  'order_specs_text_clarify',
  'order_specs_confirm',
  'order_final',
  'equipment_price_phone',
  'equipment_price_email',
  'equipment_price_verify_code',
]);

const FLOWMETER_RESUME_MESSAGE_KINDS = new Set([
  'order_specs_text_clarify',
  'order_specs_confirm',
  'equipment',
]);

function findLatestFlowmeterBotMessage(messages) {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (!msg || msg.from !== 'bot') continue;
    if (FLOWMETER_RESUME_MESSAGE_KINDS.has(msg.kind) || (msg.text || '').trim()) {
      return msg;
    }
  }
  return null;
}

function cloneFlowmeterResumeMessage(message) {
  if (!message) return null;
  const { id, time, ...rest } = message;
  return {
    ...rest,
    id: `flowmeter-resume-${Date.now()}`,
    time: new Date(),
  };
}

function isAllowedOrderSpecsFile(file) {
  if (!file) return false;
  const n = (file.name || '').toLowerCase();
  if (ORDER_SPECS_EXTS.some((ext) => n.endsWith(ext))) return true;
  const t = (file.type || '').toLowerCase();
  return (
    t === 'application/pdf' ||
    t === 'application/x-pdf' ||
    t === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  );
}

/** Временная отладка: кнопка пропуска верификации на шаге телефона (сервер принимает только при DEBUG). */
const SHOW_EQUIPMENT_PRICE_DEBUG =
  process.env.NODE_ENV === 'development' ||
  String(process.env.REACT_APP_SHOW_EQUIPMENT_PRICE_DEBUG || '').toLowerCase() === 'true';

function isAllowedLiquidTzFile(file) {
  if (!file?.name) return false;
  const n = file.name.toLowerCase();
  return LIQUID_TZ_EXTS.some((ext) => n.endsWith(ext));
}

/** accept для input[type=file] на шаге ТЗ */
const LIQUID_TZ_ACCEPT =
  '.pdf,.doc,.docx,.txt,.zip,.rar,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,application/zip,application/x-zip-compressed,application/x-rar-compressed,application/vnd.rar';

function isLiquidTzBotMessage(msg) {
  if (!msg || msg.from !== 'bot') return false;
  if (msg.kind === 'liquid_tz_prompt') return true;
  const t = msg.text || '';
  return t.includes('техническое задание') && t.includes('10 МБ') && t.includes('Далее');
}

/** Карточка-подсказка для шага загрузки ТЗ (стиль как в макете). */
function LiquidTzPromptCard({ templateUrl }) {
  const previewBox = (
    <div className="chat-widget__pdf-preview-box chat-widget__tz-preview-box">
      <div className="chat-widget__pdf-placeholder">
        <span className="chat-widget__pdf-label">DOC</span>
      </div>
      <span className="chat-widget__pdf-download" aria-hidden="true">
        ↓
      </span>
    </div>
  );

  return (
    <div className="chat-widget__tz-card" role="region" aria-label="Загрузка технического задания">
      <div className="chat-widget__tz-clipboard-row">
        <span className="chat-widget__tz-clipboard" aria-hidden="true">
          📋
        </span>
      </div>

      <div className="chat-widget__tz-card-headline">Прикрепите своё ТЗ или заполните опросный лист</div>

      <div className="chat-widget__tz-card-sub">
        <p className="chat-widget__tz-card-sub-p">
          Допустимые форматы: PDF, DOC, DOCX, TXT, ZIP, RAR — до 10 МБ.
        </p>
        <p className="chat-widget__tz-card-sub-p">
          Документ можно подписать электронной подписью или вручную — по желанию. Без вложения нажмите
          «Далее».
        </p>
      </div>

      <a
        className="chat-widget__tz-download-anchor"
        href={templateUrl}
        target="_blank"
        rel="noopener noreferrer"
        download
        title="Скачать опросный лист (Опросный_лист_PURS.doc)"
      >
        {previewBox}
      </a>

      <div className="chat-widget__tz-file-caption">
        <div className="chat-widget__tz-nested-title">Опросный лист (шаблон)</div>
        <div className="chat-widget__tz-nested-desc">
          Скачайте шаблон, заполните его и прикрепите файл ниже кнопкой «📎». Если используете своё ТЗ —
          просто прикрепите его или нажмите «Далее».
        </div>
      </div>
    </div>
  );
}

/** Карточка контактов после успешной заявки на установку «жидкость». */
function LiquidVerificationConsultCard() {
  return (
    <div className="chat-widget__liquid-consult" role="region" aria-label="Контакты для консультации">
      <div className="chat-widget__liquid-consult-icon" aria-hidden="true">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M7 9h10v1.5H7V9zm0 3h6v1.5H7V12z"
            fill="rgba(30,58,95,0.35)"
          />
          <path
            d="M5 5.5h14a1.5 1.5 0 011.5 1.5v10A1.5 1.5 0 0119 18.5H5A1.5 1.5 0 013.5 17V7A1.5 1.5 0 015 5.5z"
            stroke="rgba(30,58,95,0.45)"
            strokeWidth="1.35"
          />
          <path
            d="M8 21.5h8"
            stroke="rgba(30,58,95,0.35)"
            strokeWidth="1.35"
            strokeLinecap="round"
          />
        </svg>
      </div>
      <div className="chat-widget__liquid-consult-title">Есть вопросы? Хотите получить консультацию?</div>
      <p className="chat-widget__liquid-consult-sub">Позвоните или напишите нам!</p>
      <div className="chat-widget__liquid-consult-pills">
        <a className="chat-widget__liquid-consult-pill" href="tel:+78632037780">
          <span className="chat-widget__liquid-consult-pill-icon chat-widget__liquid-consult-pill-icon--phone" aria-hidden="true">
            📞
          </span>
          <span>+7 (863) 203-77-80</span>
        </a>
        <a className="chat-widget__liquid-consult-pill" href="mailto:info@turbo-don.ru">
          <span className="chat-widget__liquid-consult-pill-icon chat-widget__liquid-consult-pill-icon--mail" aria-hidden="true">
            ✉️
          </span>
          <span>info@turbo-don.ru</span>
        </a>
      </div>
    </div>
  );
}

/** Число из строки спецификации («300», «7,35 МПа», «1-2,5%»). preferMax — для диапазонов взять максимум. */
function numberFromSpecValue(value, { preferMax = false } = {}) {
  if (value == null || value === '') return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const s = String(value).trim().replace(/,/g, '.');
  const matches = s.match(/-?\d+(?:\.\d+)?/g);
  if (!matches?.length) return null;
  const nums = matches.map((m) => Number(m)).filter((n) => Number.isFinite(n));
  if (!nums.length) return null;
  return preferMax ? Math.max(...nums) : nums[0];
}

function jsonNumber(value) {
  return Number.isInteger(value) ? value : value;
}

function equipmentIdFromItem(equipment) {
  const candidates = [
    equipment?.id,
    equipment?.equipment_id,
    equipment?.equipmentId,
    equipment?.code,
  ];
  const found = candidates.map((x) => (x ?? '').toString().trim()).find(Boolean);
  return found || '';
}

/** Приборы, для которых estimate-price пока недоступен. */
const EQUIPMENT_IDS_WITHOUT_PRICE = new Set(['gfg2']);

function isEquipmentPriceUnavailable(equipment) {
  const id = equipmentIdFromItem(equipment).toLowerCase();
  return EQUIPMENT_IDS_WITHOUT_PRICE.has(id);
}

function buildPriceUnavailableMessage(equipment) {
  const name = (equipment?.model || equipment?.name || 'выбранное оборудование').trim();
  return (
    `К сожалению, ориентировочный прайс на оборудование «${name}» пока недоступен. ` +
    'Для расчёта стоимости обратитесь к менеджеру.'
  );
}

/** Восстановить черновик из таблицы подтверждения в чате. */
function orderSpecsRowsToDraft(rows) {
  if (!Array.isArray(rows)) return null;
  const draft = {};
  for (const row of rows) {
    if (!row?.key) continue;
    const v = (row.value ?? '').toString().trim();
    if (!v || v === '—') continue;
    draft[row.key] = v;
  }
  return Object.keys(draft).length ? normalizeSpecs(draft) : null;
}

function hasUsableOrderSpecs(specs) {
  const s = normalizeSpecs(specs || {});
  return (
    numberFromSpecValue(s.diameter ?? s.dn) != null &&
    numberFromSpecValue(s.pressureMax ?? s.pressure_max ?? s.pressure_max_mpa, { preferMax: true }) !=
      null &&
    numberFromSpecValue(s.accuracy) != null
  );
}

/** Снимок спецификации: ref → сообщение со слайдером → таблица подтверждения. */
function resolveOrderSpecsForPrice(messages, refSnapshot) {
  if (hasUsableOrderSpecs(refSnapshot)) {
    return normalizeSpecs(refSnapshot);
  }
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (m.kind === 'equipment' && m.orderSpecs && hasUsableOrderSpecs(m.orderSpecs)) {
      return normalizeSpecs(m.orderSpecs);
    }
  }
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (m.kind === 'order_specs_confirm' && m.orderSpecsRows?.length) {
      const fromTable = orderSpecsRowsToDraft(m.orderSpecsRows);
      if (hasUsableOrderSpecs(fromTable)) return fromTable;
    }
  }
  return normalizeSpecs(refSnapshot || {});
}

function resolveEquipmentForPrice(equipmentRef, messages) {
  if (equipmentRef && equipmentIdFromItem(equipmentRef)) {
    return equipmentRef;
  }
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (m.kind === 'equipment' && Array.isArray(m.equipment) && m.equipment.length) {
      const saved = m.currentEquipment;
      if (saved && equipmentIdFromItem(saved)) return saved;
      const first = m.equipment[0];
      if (first && equipmentIdFromItem(first)) return first;
    }
  }
  return equipmentRef || null;
}

function buildEstimatePriceBody(equipment, specs) {
  const s = normalizeSpecs(specs || {});
  const eq = equipment && typeof equipment === 'object' ? equipment : {};
  const eqSpecs = eq.specs && typeof eq.specs === 'object' ? eq.specs : {};

  const id = equipmentIdFromItem(eq);
  const name = (eq.name || eq.model || '').toString().trim();

  let diameter = numberFromSpecValue(s.diameter ?? s.dn);
  let pressureMax = numberFromSpecValue(
    s.pressureMax ?? s.pressure_max ?? s.pressure_max_mpa,
    { preferMax: true },
  );
  if (pressureMax == null) {
    pressureMax = numberFromSpecValue(s.pressureMin ?? s.pressure_min, { preferMax: true });
  }
  if (pressureMax == null && eqSpecs.pressureRange) {
    pressureMax = numberFromSpecValue(eqSpecs.pressureRange, { preferMax: true });
  }

  let accuracy = numberFromSpecValue(s.accuracy);
  if (accuracy == null && eqSpecs.accuracy) {
    accuracy = numberFromSpecValue(eqSpecs.accuracy);
  }

  if (!id || !name || diameter == null || pressureMax == null || accuracy == null) {
    if (process.env.NODE_ENV === 'development') {
      // eslint-disable-next-line no-console
      console.warn('[estimate-price] не хватает данных для запроса:', {
        id,
        name,
        diameter,
        pressureMax,
        accuracy,
        specs: s,
        equipment: { id: eq.id, model: eq.model, name: eq.name },
      });
    }
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

function buildTkpSpecsBody(specs) {
  const s = normalizeSpecs(specs || {});
  const dn = numberFromSpecValue(s.dn ?? s.diameter);
  const temperatureMax = numberFromSpecValue(
    s.tempMediumMax ?? s.temperature_max ?? s.temperatureMax,
  );
  const pressureMax = numberFromSpecValue(
    s.pressureMax ?? s.pressure_max ?? s.pressure_max_mpa,
  );
  const accuracy = numberFromSpecValue(s.accuracy);
  const body = {};

  if (dn != null) body.dn = Math.trunc(dn);
  if (temperatureMax != null) body.temperature_max = jsonNumber(temperatureMax);
  if (pressureMax != null) body.pressure_max_mpa = jsonNumber(pressureMax);
  if (accuracy != null) body.accuracy = jsonNumber(accuracy);

  return body;
}

/** Тайминги PDF → OCR → LLM в консоль браузера (сервер + оценка загрузки файла). */
function logOrderSpecsPipelineTiming(serverTiming, clientStartedAt) {
  if (!serverTiming || typeof serverTiming !== 'object') return;
  const ocrMs = Number(serverTiming.ocr_ms) || 0;
  const llmMs = Number(serverTiming.llm_ms) || 0;
  const pipelineMs = Number(serverTiming.pipeline_ms) || 0;
  const ocrChars = serverTiming.ocr_chars ?? 0;
  const clientTotalMs =
    clientStartedAt != null ? Math.round(performance.now() - clientStartedAt) : null;
  const uploadMs =
    clientTotalMs != null && pipelineMs > 0
      ? Math.max(0, Math.round(clientTotalMs - pipelineMs))
      : null;

  // eslint-disable-next-line no-console
  console.log('[PDF → OCR → LLM] тайминги обработки заказа:');
  // eslint-disable-next-line no-console
  console.log(
    `  OCR: ${ocrMs} ms (${(ocrMs / 1000).toFixed(1)} с) — от начала обработки PDF на сервере до отправки текста в LLM`,
  );
  // eslint-disable-next-line no-console
  console.log(
    `  LLM: ${llmMs} ms (${(llmMs / 1000).toFixed(1)} с) — от запроса в LM Studio до получения ответа`,
  );
  // eslint-disable-next-line no-console
  console.log(
    `  Сервер (OCR + LLM + разбор JSON): ${pipelineMs} ms (${(pipelineMs / 1000).toFixed(1)} с), символов OCR: ${ocrChars}`,
  );
  if (clientTotalMs != null) {
    // eslint-disable-next-line no-console
    console.log(
      `  Клиент (отправка PDF → ответ API): ${clientTotalMs} ms (${(clientTotalMs / 1000).toFixed(1)} с)`,
    );
    if (uploadMs != null && uploadMs > 0) {
      // eslint-disable-next-line no-console
      console.log(
        `  Загрузка файла и сеть (оценка): ${uploadMs} ms (${(uploadMs / 1000).toFixed(1)} с)`,
      );
    }
  }
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
    return 'http://192.168.5.49:8010';
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

function buildTkpPdfBody(quote, accessories, contact, specs) {
  if (!quote?.equipmentId || !quote?.equipmentName) return null;
  const price = quote.priceRub ?? parsePriceRub(quote.priceDisplay);
  if (price == null || !Number.isFinite(price)) return null;
  return {
    equipment_name: quote.equipmentName,
    equipment_id: quote.equipmentId,
    price,
    phone: contact?.phone || '',
    email: contact?.email || '',
    ...buildTkpSpecsBody(specs),
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

function fileNameFromUrl(url) {
  try {
    const pathname = new URL(url).pathname;
    const last = pathname.split('/').filter(Boolean).pop();
    return last ? decodeURIComponent(last) : '';
  } catch {
    const last = String(url || '').split('/').filter(Boolean).pop();
    return last ? decodeURIComponent(last) : '';
  }
}

function AttachmentPdfCard({ url, filename, title = 'Файл для скачивания' }) {
  if (!url) return null;
  const displayName = filename || fileNameFromUrl(url) || 'Вложение.pdf';
  return (
    <div className="chat-widget__pdf-card chat-widget__pdf-card--attachment">
      <a
        className="chat-widget__pdf-preview-box"
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        download
        title={`Скачать ${displayName}`}
      >
        <div className="chat-widget__pdf-placeholder">
          <span className="chat-widget__pdf-label">PDF</span>
        </div>
        <span className="chat-widget__pdf-download" aria-hidden="true">
          ↓
        </span>
      </a>
      <div className="chat-widget__pdf-name">{title}</div>
      <div className="chat-widget__tz-nested-desc">{displayName}</div>
    </div>
  );
}

function faqActionTypeLabel(type) {
  if (type === 'phone') return 'TEL';
  if (type === 'email') return 'MAIL';
  if (type === 'file') return 'PDF';
  return 'LINK';
}

function FaqCard({ card }) {
  if (!card) return null;
  const actions = Array.isArray(card.actions) ? card.actions.filter(Boolean) : [];
  return (
    <div className="chat-widget__faq-card" role="region" aria-label={card.title || 'Справочная информация'}>
      <div className="chat-widget__faq-card-head">
        <div className="chat-widget__faq-card-kicker">Справочная информация</div>
        <div className="chat-widget__faq-card-title">{card.title || 'Ответ'}</div>
      </div>
      {card.description ? <div className="chat-widget__faq-card-desc">{card.description}</div> : null}
      {actions.length > 0 ? (
        <div className="chat-widget__faq-card-actions">
          {actions.map((action, index) => {
            const href = action.href || '';
            const isDisabled = !href && action.type !== 'text';
            const content = (
              <>
                <span className={`chat-widget__faq-action-badge chat-widget__faq-action-badge--${action.type || 'url'}`}>
                  {faqActionTypeLabel(action.type)}
                </span>
                <span className="chat-widget__faq-action-text">
                  <span className="chat-widget__faq-action-label">{action.label || action.value || 'Открыть'}</span>
                  {action.value && action.value !== action.label ? (
                    <span className="chat-widget__faq-action-value">{action.value}</span>
                  ) : null}
                </span>
              </>
            );
            if (isDisabled) {
              return (
                <div className="chat-widget__faq-action chat-widget__faq-action--disabled" key={`${action.type || 'text'}-${index}`}>
                  {content}
                </div>
              );
            }
            return (
              <a
                className="chat-widget__faq-action"
                key={`${action.type || 'url'}-${index}`}
                href={href}
                target={action.type === 'phone' || action.type === 'email' ? undefined : '_blank'}
                rel={action.type === 'phone' || action.type === 'email' ? undefined : 'noopener noreferrer'}
                download={action.type === 'file' ? true : undefined}
              >
                {content}
              </a>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function AccessoriesSelector({ items, selectedIds, onToggle }) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const selectedSet = new Set(selectedIds || []);

  return (
    <div className="chat-widget__accessories">
      <div className="chat-widget__accessories-title">Выберите дополнительные комплектующие</div>
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
  const [urlIndex, setUrlIndex] = useState(0);

  const n = Array.isArray(items) ? items.length : 0;
  const item = n > 0 ? items[idx] || {} : {};
  const label = (item.model || item.name || '').trim() || '—';
  const single = n === 1;

  const imageCandidates = useMemo(
    () => [
      ...getBundledEquipmentImageUrls(item),
      ...getEquipmentImageCandidateUrlsFromItem(item),
    ],
    [item.id, item.image, item.image_url, item.image_path]
  );
  const src = imageCandidates[urlIndex] || '';

  useEffect(() => {
    setImageFailed(false);
    setUrlIndex(0);
  }, [idx, items]);

  useEffect(() => {
    if (typeof onCurrentItemChange !== 'function') return;
    onCurrentItemChange(n > 0 ? items[idx] || {} : {});
  }, [idx, items, n, onCurrentItemChange]);

  if (!Array.isArray(items) || items.length === 0) return null;

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
            key={`${src}-${urlIndex}`}
            className="chat-widget__equipment-img"
            src={src}
            alt={label}
            onError={() => {
              if (process.env.NODE_ENV === 'development') {
                // eslint-disable-next-line no-console
                console.warn('[equipment image] load failed, tried:', src, 'raw:', item?.image);
              }
              if (urlIndex + 1 < imageCandidates.length) {
                setUrlIndex((i) => i + 1);
              } else {
                setImageFailed(true);
              }
            }}
          />
        ) : null}
        {(!src || imageFailed) && (
          <div className="chat-widget__equipment-placeholder">
            {imageFailed
              ? 'Превью не загрузилось (проверьте поле image в ответе и файл в templates/static/equipment на сервере Django).'
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

const CHAT_HEIGHT_STORAGE_KEY = 'turbo-don-chat-window-height';
const DEFAULT_CHAT_HEIGHT = 520;
const MIN_CHAT_HEIGHT = 360;

const CHAT_GREETING_TEASER_TEXT =
  'Здравствуйте! Помогу подобрать оборудование или ответить на ваши вопросы.';

function getMaxChatHeight() {
  return Math.max(MIN_CHAT_HEIGHT, window.innerHeight - 120);
}

function readStoredChatHeight() {
  try {
    const stored = Number(localStorage.getItem(CHAT_HEIGHT_STORAGE_KEY));
    if (Number.isFinite(stored) && stored >= MIN_CHAT_HEIGHT) {
      return Math.min(stored, getMaxChatHeight());
    }
  } catch {
    /* ignore */
  }
  return Math.min(DEFAULT_CHAT_HEIGHT, getMaxChatHeight());
}

function clampChatHeight(height) {
  return Math.min(getMaxChatHeight(), Math.max(MIN_CHAT_HEIGHT, height));
}

export function ChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [showGreetingTeaser, setShowGreetingTeaser] = useState(false);
  const [chatWindowHeight, setChatWindowHeight] = useState(readStoredChatHeight);
  const [isResizingChat, setIsResizingChat] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [typingStage, setTypingStage] = useState('');
  const [typingDetailsOpen, setTypingDetailsOpen] = useState(false);
  const [chatId, setChatId] = useState(null);
  const hasMessages = useRef(false);
  const fileInputRef = useRef(null);
  const inputRef = useRef(null);
  const orderFileDragDepthRef = useRef(0);
  /** Защита от двойного нажатия «Получить цену» / debug на шаге телефона (дубли одного и того же ответа бота). */
  const equipmentPriceActionLockRef = useRef(false);

  const [selectedImage, setSelectedImage] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [selectedPdf, setSelectedPdf] = useState(null);
  const [isOrderFileDragActive, setIsOrderFileDragActive] = useState(false);

  const [hintState, setHintState] = useState({
    currentState: 'start',
    hints: [],
    showBack: false,
    isFinal: false,
    expectsInput: false,
    hintsOnly: false,
  });
  const [hintLocked, setHintLocked] = useState(false);
  const [isEquipmentPriceActionBusy, setIsEquipmentPriceActionBusy] = useState(false);

  const isOrderPdfStep = hintState.currentState === 'order_pdf_request';
  const isFlowmeterScenario = FLOWMETER_HINT_STATES.has(hintState.currentState);
  const isLiquidTzStep = hintState.currentState === 'verification_installations_liquid_tz';
  const isLiquidTzCommentsStep =
    hintState.currentState === 'verification_installations_liquid_tz_comments';
  const isGasSpuApplicationTzStep =
    hintState.currentState === 'verification_installations_gas_application_tz';
  const isGasSpuApplicationTzCommentsStep =
    hintState.currentState === 'verification_installations_gas_application_tz_comments';
  const isGasSpuApplicationStep =
    hintState.currentState === 'verification_installations_gas_application' ||
    hintState.currentState === 'verification_installations_gas_application_contact' ||
    isGasSpuApplicationTzStep ||
    isGasSpuApplicationTzCommentsStep;
  const isLiquidTzLikeStep = isLiquidTzStep || isGasSpuApplicationTzStep;
  const fileInputAccept = isOrderPdfStep
    ? ORDER_SPECS_ACCEPT
    : isLiquidTzLikeStep
      ? LIQUID_TZ_ACCEPT
      : 'image/*';
  const attachButtonTitle = isOrderPdfStep
    ? 'Прикрепить PDF или DOCX'
    : isLiquidTzLikeStep
      ? 'Прикрепить ТЗ (PDF, DOC, DOCX, TXT, ZIP, RAR до 10 МБ)'
      : 'Прикрепить фото';

  /** Пока показан слайдер оборудования — ждём выбор, подсказки (как в order_final) не показываем. */
  const [awaitingEquipmentSelection, setAwaitingEquipmentSelection] = useState(false);
  /** Текущая карточка на слайдере (для «Получить цену»). */
  const sliderEquipmentRef = useRef(null);
  /** Спецификация из PDF (для расчёта цены на :8010), заполняется при ответе 1С. */
  const lastOrderSpecsRef = useRef(null);
  const [showExactCostHint, setShowExactCostHint] = useState(false);
  const [showTkpPdfHint, setShowTkpPdfHint] = useState(false);
  const [flowmeterResume, setFlowmeterResume] = useState(null);
  const [isSelectingAccessories, setIsSelectingAccessories] = useState(false);
  /** На слайдере/аксессуарах не показываем меню order_final («Расходомеры», «Продажа»…). */
  const footerScenarioHints =
    awaitingEquipmentSelection || isSelectingAccessories || showExactCostHint || showTkpPdfHint
      ? []
      : hintState.hints || [];
  const exactCostBodyRef = useRef(null);
  const estimateQuoteRef = useRef(null);
  const pendingEstimateBodyRef = useRef(null);
  const verifiedContactRef = useRef({ phone: '', email: '' });
  /** Сценарий «Поверочные установки» → «Жидкость»: ФИО и контакт (почта или телефон) для последующих шагов. */
  const liquidInstallationLeadRef = useRef({
    fullName: '',
    email: '',
    phone: '',
    tzAttachmentUrl: '',
    tzFileName: '',
    tzComments: '',
  });
  /** Сценарий «СПУ газ — оставить заявку» (анкета как у «жидкости»). */
  const gasSpuApplicationLeadRef = useRef({
    fullName: '',
    email: '',
    phone: '',
    tzAttachmentUrl: '',
    tzFileName: '',
    tzComments: '',
  });
  /** Сценарий «Бытовые счётчики газа»: выбранные позиции и контактные данные заявки. */
  const householdGasLeadRef = useRef({
    fullName: '',
    email: '',
    phone: '',
    organization: '',
    comment: '',
    selectedItems: [],
  });
  /**
   * Временное хранение файла ТЗ на шаге «жидкость»: выбранный File до отправки в чат;
   * после успешного POST — URL и имя вложения с сервера (для последующих запросов).
   */
  const liquidTzFileRef = useRef({
    file: null,
    fileName: '',
    uploadedUrl: '',
    uploadedName: '',
  });
  /** Пошаговый подбор СПУ (газ): сервер возвращает обновлённый JSON в gas_spu_selection. */
  const gasSpuRef = useRef({});
  const selectedAccessoriesRef = useRef([]);
  const [selectedAccessoryIds, setSelectedAccessoryIds] = useState([]);

  const beginTyping = useCallback((stage) => {
    const s = (stage && String(stage).trim()) || 'Обрабатываю запрос…';
    console.log('[Чатбот]', s);
    setTypingStage(s);
    setTypingDetailsOpen(false);
    setIsTyping(true);
  }, []);

  const updateTypingStage = useCallback((stage) => {
    const s = (stage && String(stage).trim()) || 'Обрабатываю запрос…';
    console.log('[Чатбот]', s);
    setTypingStage(s);
  }, []);

  const endTyping = useCallback(() => {
    setIsTyping(false);
    setTypingStage('');
    setTypingDetailsOpen(false);
  }, []);

  const toggleTypingDetails = useCallback(() => {
    setTypingDetailsOpen((open) => !open);
  }, []);

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

  /** Главное меню (как при открытии чата): GET /api/hints/?state=start */
  const applyMainMenuHints = useCallback(async () => {
    try {
      const hintsResponse = await getHints('start');
      const hintsData = hintsResponse.data;
      setHintState({
        currentState: hintsData.current_state,
        hints: hintsData.hints || [],
        showBack: hintsData.show_back,
        isFinal: hintsData.is_final,
        expectsInput: hintsData.expects_input,
        hintsOnly: hintsData.hints_only ?? false,
      });
    } catch (error) {
      console.error('getHints(start) после заявки:', error);
      const h = FALLBACK_HINTS_START;
      setHintState({
        currentState: h.current_state,
        hints: h.hints || [],
        showBack: h.show_back,
        isFinal: h.is_final,
        expectsInput: h.expects_input,
        hintsOnly: h.hints_only ?? false,
      });
    }
    setHintLocked(false);
  }, []);

  /** После выдачи ТКП: сброс сценария подбора и главное меню подсказок. */
  const resetAfterTkpScenario = useCallback(() => {
    setShowTkpPdfHint(false);
    setIsSelectingAccessories(false);
    setShowExactCostHint(false);
    setAwaitingEquipmentSelection(false);
    setSelectedAccessoryIds([]);
    selectedAccessoriesRef.current = [];
    sliderEquipmentRef.current = null;
    estimateQuoteRef.current = null;
    exactCostBodyRef.current = null;
    pendingEstimateBodyRef.current = null;
  }, []);

  const resetRefsAfterSubmittedApplication = useCallback(() => {
    householdGasLeadRef.current = {
      fullName: '',
      email: '',
      phone: '',
      organization: '',
      comment: '',
      selectedItems: [],
    };
    liquidInstallationLeadRef.current = {
      fullName: '',
      email: '',
      phone: '',
      tzAttachmentUrl: '',
      tzFileName: '',
      tzComments: '',
    };
    gasSpuApplicationLeadRef.current = {
      fullName: '',
      email: '',
      phone: '',
      tzAttachmentUrl: '',
      tzFileName: '',
      tzComments: '',
    };
    liquidTzFileRef.current = {
      file: null,
      fileName: '',
      uploadedUrl: '',
      uploadedName: '',
    };
    gasSpuRef.current = {};
    setAwaitingEquipmentSelection(false);
    sliderEquipmentRef.current = null;
  }, []);

  /** Заявка с карточкой контактов (как на скрине): завершить сценарий на сервере и показать подсказки главной. */
  const finishScenarioWithContactCard = useCallback(
    async (activeChatId) => {
      resetRefsAfterSubmittedApplication();
      if (activeChatId != null) {
        finalizeChat(activeChatId).catch((err) => console.error('finalizeChat:', err));
      }
      await applyMainMenuHints();
    },
    [applyMainMenuHints, resetRefsAfterSubmittedApplication],
  );

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
        hintsOnly: hintsData.hints_only ?? false,
      });

      setMessages([
        {
          id: 1,
          from: 'bot',
          text:
            hintsData.bot_message ||
            'Здравствуйте! Я виртуальный помощник сервиса «Турбо-дон чат». Готов помочь с подбором оборудования по Вашим параметрам и ответить на вопросы по ассортименту и характеристикам изделий. Выберите раздел ниже или опишите задачу в сообщении.',
          time: new Date(),
        },
      ]);

      setHintLocked(false);
      setAwaitingEquipmentSelection(false);
      sliderEquipmentRef.current = null;
      lastOrderSpecsRef.current = null;
      setFlowmeterResume(null);
      exactCostBodyRef.current = null;
      estimateQuoteRef.current = null;
      pendingEstimateBodyRef.current = null;
      verifiedContactRef.current = { phone: '', email: '' };
      selectedAccessoriesRef.current = [];
      setShowExactCostHint(false);
      setShowTkpPdfHint(false);
      setIsSelectingAccessories(false);
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
        hintsOnly: h.hints_only ?? false,
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
      setFlowmeterResume(null);
      exactCostBodyRef.current = null;
      estimateQuoteRef.current = null;
      pendingEstimateBodyRef.current = null;
      verifiedContactRef.current = { phone: '', email: '' };
      selectedAccessoriesRef.current = [];
      setShowExactCostHint(false);
      setShowTkpPdfHint(false);
      setIsSelectingAccessories(false);
      setSelectedAccessoryIds([]);
    }
  }, []);

  useEffect(() => {
    if (hintState.hintsOnly) {
      setInputValue('');
    }
  }, [hintState.hintsOnly, hintState.currentState]);

  const adjustInputHeight = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const nextHeight = Math.min(
      Math.max(el.scrollHeight, INPUT_MIN_HEIGHT_PX),
      INPUT_MAX_HEIGHT_PX,
    );
    el.style.height = `${nextHeight}px`;
    el.style.overflowY = el.scrollHeight > INPUT_MAX_HEIGHT_PX ? 'auto' : 'hidden';
  }, []);

  useEffect(() => {
    adjustInputHeight();
  }, [inputValue, adjustInputHeight, hintState.hintsOnly, hintState.currentState]);

  useEffect(() => {
    if (!isOrderPdfStep) {
      orderFileDragDepthRef.current = 0;
      setIsOrderFileDragActive(false);
    }
  }, [isOrderPdfStep]);

  const handleInputChange = (e) => {
    setInputValue(e.target.value);
    requestAnimationFrame(adjustInputHeight);
  };

  useEffect(() => {
    initializeChat();
  }, [initializeChat]);

  useEffect(() => {
    const timer = window.setTimeout(() => setShowGreetingTeaser(true), 2000);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (isOpen) setShowGreetingTeaser(false);
  }, [isOpen]);

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

  useEffect(() => {
    const onViewportResize = () => {
      setChatWindowHeight((h) => clampChatHeight(h));
    };
    window.addEventListener('resize', onViewportResize);
    return () => window.removeEventListener('resize', onViewportResize);
  }, []);

  const handleChatResizePointerDown = useCallback(
    (e) => {
      e.preventDefault();
      const startY = e.clientY;
      const startHeight = chatWindowHeight;
      setIsResizingChat(true);
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'ns-resize';

      const onMove = (ev) => {
        setChatWindowHeight(clampChatHeight(startHeight + (startY - ev.clientY)));
      };
      const onUp = () => {
        setIsResizingChat(false);
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
        document.removeEventListener('pointercancel', onUp);
        setChatWindowHeight((h) => {
          try {
            localStorage.setItem(CHAT_HEIGHT_STORAGE_KEY, String(h));
          } catch {
            /* ignore */
          }
          return h;
        });
      };

      document.addEventListener('pointermove', onMove);
      document.addEventListener('pointerup', onUp);
      document.addEventListener('pointercancel', onUp);
    },
    [chatWindowHeight],
  );

  const handleOrderSpecsEdit = async (row) => {
    if (!row?.key || isTyping) return;
    const label = row.label || row.key;
    const userMessage = {
      id: Date.now(),
      from: 'user',
      text: `Изменить: ${label}`,
      time: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);
    hasMessages.current = true;
    beginTyping('Открываю редактирование параметра…');
    try {
      const id = await ensureChatId();
      const response = await createMessage(id, {
        content: userMessage.text,
        hint_state: hintState.currentState,
        is_hint_selection: false,
        hint_locked: hintLocked,
        order_specs_edit_field: row.key,
      });
      applyHintStateFromResponse(response.data, setHintState, setHintLocked);
      const botMessages = response.data.messages?.filter((msg) => !msg.is_user) || [];
      if (shouldShowOrderSpecsBotMessage(response, botMessages)) {
        const firstBotMessage = botMessages[0] || {};
        const botMsg = {
          id: firstBotMessage?.id || Date.now() + 1,
          from: 'bot',
          text: firstBotMessage?.content || '',
          time: new Date(firstBotMessage?.created_at || Date.now()),
          ...(firstBotMessage.attachment_url ? { attachmentUrl: firstBotMessage.attachment_url } : {}),
          ...(firstBotMessage.attachment_name ? { pdfName: firstBotMessage.attachment_name } : {}),
        };
        setMessages((prev) => [...prev, enrichBotMessage(botMsg, response)]);
      } else if (botMessages.length > 0 && (botMessages[0].content || '').trim()) {
        const firstBotMessage = botMessages[0] || {};
        const fallbackMsg = {
          id: firstBotMessage.id,
          from: 'bot',
          text: firstBotMessage.content,
          time: new Date(firstBotMessage.created_at),
          ...(firstBotMessage.attachment_url ? { attachmentUrl: firstBotMessage.attachment_url } : {}),
          ...(firstBotMessage.attachment_name ? { pdfName: firstBotMessage.attachment_name } : {}),
        };
        setMessages((prev) => [...prev, enrichBotMessage(fallbackMsg, response)]);
      }
    } catch (error) {
      console.error('order_specs edit:', error);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          from: 'bot',
          text: 'Не удалось открыть редактирование. Попробуйте ещё раз.',
          time: new Date(),
        },
      ]);
    } finally {
      endTyping();
    }
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
    setFlowmeterResume(null);

    hasMessages.current = true;
    beginTyping('Отправляю выбранную подсказку на сервер…');

    try {
      const id = await ensureChatId();
      const hintPayload = {
        content: hint.text,
        hint_state: hintState.currentState,
        is_hint_selection: true,
        hint_locked: hintLocked,
      };
      if (hintState.currentState === 'verification_installations_liquid_tz') {
        const r = liquidInstallationLeadRef.current;
        if (r.fullName) {
          hintPayload.liquid_installation_lead = {
            full_name: r.fullName,
            email: r.email || '',
            phone: r.phone || '',
            tz_attachment_url: r.tzAttachmentUrl || '',
            tz_file_name: r.tzFileName || '',
            tz_comments: r.tzComments || '',
          };
        }
      }
      if (hintState.currentState === 'verification_installations_gas_application_tz') {
        const r = gasSpuApplicationLeadRef.current;
        if (r.fullName) {
          hintPayload.gas_spu_application_lead = {
            full_name: r.fullName,
            email: r.email || '',
            phone: r.phone || '',
            tz_attachment_url: r.tzAttachmentUrl || '',
            tz_file_name: r.tzFileName || '',
            tz_comments: r.tzComments || '',
          };
        }
      }
      if (isGasSpuApplicationStep) {
        hintPayload.gas_spu_selection = { ...gasSpuRef.current };
      }
      if (hintState.currentState === 'verification_installations_gas') {
        hintPayload.gas_spu_selection = { ...gasSpuRef.current };
      }
      const response = await createMessage(id, hintPayload);
      updateTypingStage('Ответ сервера получен, обновляю чат…');
      setAwaitingEquipmentSelection(false);

      if (response.data.hint_state) {
        const newState = response.data.hint_state;
        if (newState.current_state === 'verification_installations_gas_application') {
          gasSpuApplicationLeadRef.current = {
            fullName: '',
            email: '',
            phone: '',
            tzAttachmentUrl: '',
            tzFileName: '',
            tzComments: '',
          };
          liquidTzFileRef.current = {
            file: null,
            fileName: '',
            uploadedUrl: '',
            uploadedName: '',
          };
        }
        if (newState.current_state === 'verification_installations_liquid') {
          liquidInstallationLeadRef.current = {
            fullName: '',
            email: '',
            phone: '',
            tzAttachmentUrl: '',
            tzFileName: '',
            tzComments: '',
          };
          liquidTzFileRef.current = {
            file: null,
            fileName: '',
            uploadedUrl: '',
            uploadedName: '',
          };
        }
        if (newState.current_state === 'equipment_household_gas_dev') {
          householdGasLeadRef.current = {
            fullName: '',
            email: '',
            phone: '',
            organization: '',
            comment: '',
            selectedItems: [],
          };
        }
        if (newState.current_state === 'verification_installations') {
          gasSpuRef.current = {};
        }
        setHintState({
          currentState: newState.current_state,
          hints: newState.hints || [],
          showBack: newState.show_back,
          isFinal: newState.is_final,
          expectsInput: newState.expects_input,
          hintsOnly: newState.hints_only ?? false,
        });

        if (newState.current_state === 'start' || newState.is_final) {
          setHintLocked(false);
        } else if (newState.hint_locked !== undefined) {
          setHintLocked(newState.hint_locked);
        } else {
          setHintLocked(true);
        }
      } else {
        setHintLocked(true);
      }

      if (response.data.liquid_installation_lead) {
        const lead = response.data.liquid_installation_lead;
        const prev = liquidInstallationLeadRef.current;
        liquidInstallationLeadRef.current = {
          fullName: lead.full_name || prev.fullName || '',
          email: lead.email || prev.email || '',
          phone: lead.phone || prev.phone || '',
          tzAttachmentUrl: lead.tz_attachment_url || prev.tzAttachmentUrl || '',
          tzFileName: lead.tz_file_name || prev.tzFileName || '',
          tzComments:
            lead.tz_comments !== undefined && lead.tz_comments !== null
              ? String(lead.tz_comments)
              : prev.tzComments || '',
        };
      }
      if (response.data.gas_spu_application_lead) {
        const lead = response.data.gas_spu_application_lead;
        const prev = gasSpuApplicationLeadRef.current;
        gasSpuApplicationLeadRef.current = {
          fullName: lead.full_name || prev.fullName || '',
          email: lead.email || prev.email || '',
          phone: lead.phone || prev.phone || '',
          tzAttachmentUrl: lead.tz_attachment_url || prev.tzAttachmentUrl || '',
          tzFileName: lead.tz_file_name || prev.tzFileName || '',
          tzComments:
            lead.tz_comments !== undefined && lead.tz_comments !== null
              ? String(lead.tz_comments)
              : prev.tzComments || '',
        };
      }
      if (response.data.household_gas_lead) {
        const lead = response.data.household_gas_lead;
        const prev = householdGasLeadRef.current;
        householdGasLeadRef.current = {
          fullName: lead.full_name || prev.fullName || '',
          email: lead.email || prev.email || '',
          phone: lead.phone || prev.phone || '',
          organization:
            lead.organization !== undefined && lead.organization !== null
              ? String(lead.organization)
              : prev.organization || '',
          comment:
            lead.comment !== undefined && lead.comment !== null
              ? String(lead.comment)
              : prev.comment || '',
          selectedItems: Array.isArray(lead.selected_items)
            ? lead.selected_items
            : prev.selectedItems || [],
        };
      }
      logSubmitHouseholdGasResponse(response);
      logSubmitSpuApplicationResponse(response);
      if (response.data.gas_spu_selection != null) {
        gasSpuRef.current = { ...response.data.gas_spu_selection };
      }
      if (response.data.gas_spu_preview) {
        const p = response.data.gas_spu_preview;
        try {
          if (typeof console.clear === 'function') {
            console.clear();
          }
        } catch (e) {
          /* ignore */
        }
        console.log('[СПУ газ] метод запроса:', p.method);
        console.log('[СПУ газ] URL:', p.url);
        console.log('[СПУ газ] тело запроса (JSON):\n', JSON.stringify(p.body ?? {}, null, 2));
        console.log(
          '[СПУ газ] Реальный POST на URL карточки выполняется на сервере Django после кнопки «Подобрать оборудование»; в Network браузера остаётся только запрос к /api/chats/.../messages/.'
        );
      }

      if (isOrderFinalWithSpecs(response.data)) {
        const specs = response.data.order_specs_json;
        try {
          updateTypingStage('Подбор оборудования (GET search-equipment)…');
          const res = await fetchSearchEquipment(specs);
          const d = res.data;
          if (d?.status === 'success' && Array.isArray(d?.equipment) && d.equipment.length > 0) {
            lastOrderSpecsRef.current = specs;
            const firstItem = d.equipment[0];
            if (firstItem) sliderEquipmentRef.current = firstItem;
            setMessages((prev) => [
              ...prev,
              {
                id: `eq-hint-${Date.now()}`,
                from: 'bot',
                kind: 'equipment',
                equipment: d.equipment,
                orderSpecs: specs,
                currentEquipment: firstItem || null,
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
          console.error('[search-equipment] ошибка:', err);
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
        if (botMessages.length > 0 && shouldShowOrderSpecsBotMessage(response, botMessages)) {
          const hs = response.data.hint_state;
          const firstBotMessage = botMessages[0] || {};
          const botMsg = {
            id: firstBotMessage.id,
            from: 'bot',
            text: firstBotMessage.content || '',
            time: new Date(firstBotMessage.created_at),
            ...(firstBotMessage.attachment_url ? { attachmentUrl: firstBotMessage.attachment_url } : {}),
            ...(firstBotMessage.attachment_name ? { pdfName: firstBotMessage.attachment_name } : {}),
          };
          if (
            response.data.submit_verification_liquid?.status === 'success' ||
            response.data.submit_household_gas?.status === 'success' ||
            response.data.submit_spu_application?.status === 'success'
          ) {
            botMsg.kind = 'liquid_verification_contact';
          } else if (
            hs?.current_state === 'verification_installations_liquid_tz' ||
            hs?.current_state === 'verification_installations_gas_application_tz'
          ) {
            botMsg.kind = 'liquid_tz_prompt';
          }
          setMessages((prev) => [...prev, enrichBotMessage(botMsg, response)]);
        } else if (botMessages.length > 0 && (botMessages[0].content || '').trim()) {
          const firstBotMessage = botMessages[0] || {};
          const fallbackMsg = {
            id: firstBotMessage.id,
            from: 'bot',
            text: firstBotMessage.content,
            time: new Date(firstBotMessage.created_at),
            ...(firstBotMessage.attachment_url ? { attachmentUrl: firstBotMessage.attachment_url } : {}),
            ...(firstBotMessage.attachment_name ? { pdfName: firstBotMessage.attachment_name } : {}),
          };
          setMessages((prev) => [...prev, enrichBotMessage(fallbackMsg, response)]);
        }
      }

      const applicationSubmitted =
        response.data.submit_verification_liquid?.status === 'success' ||
        response.data.submit_household_gas?.status === 'success' ||
        response.data.submit_spu_application?.status === 'success';
      if (applicationSubmitted) {
        void finishScenarioWithContactCard(id);
      }
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
      endTyping();
    }
  };

  /** Примерная цена прибора (estimate-price); нужна для ТКП PDF. */
  const ensureEstimateQuote = useCallback(async () => {
    let quote = estimateQuoteRef.current;
    if (quote?.priceRub != null && Number.isFinite(quote.priceRub)) {
      return quote;
    }
    const fromDisplay = parsePriceRub(quote?.priceDisplay);
    if (fromDisplay != null && quote?.equipmentId) {
      quote = { ...quote, priceRub: fromDisplay };
      estimateQuoteRef.current = quote;
      return quote;
    }

    const eq = resolveEquipmentForPrice(sliderEquipmentRef.current, messages);
    const specs = resolveOrderSpecsForPrice(messages, lastOrderSpecsRef.current);
    const estimateBody =
      pendingEstimateBodyRef.current || buildEstimatePriceBody(eq, specs);
    if (!estimateBody) return null;
    if (isEquipmentPriceUnavailable(estimateBody.equipment)) return null;

    const estimateResponse = await postEstimatePrice(estimateBody);
    const estimateData = estimateResponse.data || {};
    const equipmentName = (
      estimateData.equipment_name ||
      estimateBody.equipment.name ||
      ''
    ).trim();
    const equipmentId = (
      estimateData.equipment_id ||
      estimateBody.equipment.id ||
      ''
    )
      .toString()
      .trim();
    const priceRub = parsePriceRub(
      estimateData.price_rub ?? estimateData.price ?? estimateData.price_display,
    );
    const priceDisplay = (estimateData.price_display || '').trim();
    if (priceRub == null) return null;

    quote = {
      equipmentName: equipmentName || estimateBody.equipment.name,
      equipmentId: equipmentId || estimateBody.equipment.id,
      priceRub,
      priceDisplay,
    };
    estimateQuoteRef.current = quote;
    return quote;
  }, [messages]);

  const runEstimatePrice = useCallback(async (estimateBody, fallbackLabel = 'оборудование') => {
    if (!estimateBody) {
      estimateBody = buildEstimatePriceBody(
        resolveEquipmentForPrice(sliderEquipmentRef.current, messages),
        resolveOrderSpecsForPrice(messages, lastOrderSpecsRef.current),
      );
    }
    if (!estimateBody) {
      exactCostBodyRef.current = null;
      estimateQuoteRef.current = null;
      selectedAccessoriesRef.current = [];
      setShowExactCostHint(false);
      setShowTkpPdfHint(false);
      setIsSelectingAccessories(false);
      setMessages((prev) => [
        ...prev,
        {
          id: `estimate-missing-${Date.now()}`,
          from: 'bot',
          text: 'Ориентировочный расчёт не выполнен: не хватает кода прибора или параметров из итоговой спецификации.',
          time: new Date(),
        },
      ]);
      return;
    }

    if (isEquipmentPriceUnavailable(estimateBody.equipment)) {
      exactCostBodyRef.current = null;
      estimateQuoteRef.current = null;
      selectedAccessoriesRef.current = [];
      setShowExactCostHint(false);
      setShowTkpPdfHint(false);
      setIsSelectingAccessories(false);
      setMessages((prev) => [
        ...prev,
        {
          id: `estimate-unavailable-${Date.now()}`,
          from: 'bot',
          text: buildPriceUnavailableMessage(estimateBody.equipment),
          time: new Date(),
        },
      ]);
      return;
    }

    try {
      console.log('[Чатбот] Запрос ориентировочной цены (estimate-price)…');
      const estimateResponse = await postEstimatePrice(estimateBody);
      console.log('[Чатбот] Ответ estimate-price получен.');
      const estimateData = estimateResponse.data || {};
      const equipmentName = (estimateData.equipment_name || estimateBody.equipment.name || fallbackLabel).trim();
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
      pendingEstimateBodyRef.current = null;
      selectedAccessoriesRef.current = [];
      setShowExactCostHint(Boolean(exactCostBodyRef.current));
      setShowTkpPdfHint(false);
      setIsSelectingAccessories(false);
      setSelectedAccessoryIds([]);
    } catch (estimateError) {
      console.error('[estimate-price] ошибка:', estimateError);
      exactCostBodyRef.current = null;
      estimateQuoteRef.current = null;
      selectedAccessoriesRef.current = [];
      setShowExactCostHint(false);
      setShowTkpPdfHint(false);
      setIsSelectingAccessories(false);
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
  }, [messages]);

  const syncSliderEquipment = useCallback((item) => {
    sliderEquipmentRef.current = item;
    if (!item || !equipmentIdFromItem(item)) return;
    setMessages((prev) => {
      let msgIdx = -1;
      for (let i = prev.length - 1; i >= 0; i -= 1) {
        if (prev[i].kind === 'equipment') {
          msgIdx = i;
          break;
        }
      }
      if (msgIdx < 0) return prev;
      const m = prev[msgIdx];
      const curId = equipmentIdFromItem(m.currentEquipment);
      const nextId = equipmentIdFromItem(item);
      if (curId && nextId && curId === nextId) return prev;
      const next = [...prev];
      next[msgIdx] = { ...m, currentEquipment: item };
      return next;
    });
  }, []);

  const handleGetPriceHint = async () => {
    if (equipmentPriceActionLockRef.current) return;
    const eq = resolveEquipmentForPrice(sliderEquipmentRef.current, messages);
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

    if (isEquipmentPriceUnavailable(eq)) {
      setMessages((prev) => [
        ...prev,
        {
          id: `estimate-unavailable-${Date.now()}`,
          from: 'bot',
          text: buildPriceUnavailableMessage(eq),
          time: new Date(),
        },
      ]);
      return;
    }

    beginTyping('Отправляю запрос «Получить цену» на сервер…');
    equipmentPriceActionLockRef.current = true;
    setIsEquipmentPriceActionBusy(true);
    try {
      const id = await ensureChatId();
      const specsForPrice = resolveOrderSpecsForPrice(messages, lastOrderSpecsRef.current);
      lastOrderSpecsRef.current = specsForPrice;
      const estimateBody = buildEstimatePriceBody(eq, specsForPrice);
      pendingEstimateBodyRef.current = estimateBody;
      if (!estimateBody) {
        setMessages((prev) => [
          ...prev,
          {
            id: `estimate-missing-pre-${Date.now()}`,
            from: 'bot',
            text:
              'Не удалось начать запрос цены: у выбранного прибора нет id или в спецификации не хватает DN, максимального давления или точности.',
            time: new Date(),
          },
        ]);
        return;
      }
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
      updateTypingStage('Ответ сервера получен, обновляю чат…');
      setAwaitingEquipmentSelection(false);

      if (response.data.hint_state) {
        const newState = response.data.hint_state;
        setHintState({
          currentState: newState.current_state,
          hints: newState.hints || [],
          showBack: newState.show_back,
          isFinal: newState.is_final,
          expectsInput: newState.expects_input,
          hintsOnly: newState.hints_only ?? false,
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
          const firstBotMessage = botMessages[0] || {};
          const botMsg = {
            id: firstBotMessage.id,
            from: 'bot',
            text: firstBotMessage.content || 'Пустой ответ сервера.',
            time: new Date(firstBotMessage.created_at),
            ...(firstBotMessage.attachment_url ? { attachmentUrl: firstBotMessage.attachment_url } : {}),
            ...(firstBotMessage.attachment_name ? { pdfName: firstBotMessage.attachment_name } : {}),
          };
          setMessages((prev) => [...prev, enrichBotMessage(botMsg, response)]);
        }
      }
      if (!estimateBody) {
        exactCostBodyRef.current = null;
        estimateQuoteRef.current = null;
        selectedAccessoriesRef.current = [];
        setShowExactCostHint(false);
        setShowTkpPdfHint(false);
        setIsSelectingAccessories(false);
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
      equipmentPriceActionLockRef.current = false;
      setIsEquipmentPriceActionBusy(false);
      endTyping();
    }
  };

  const handleDebugSkipEquipmentPriceVerify = async () => {
    if (equipmentPriceActionLockRef.current) return;
    beginTyping('Debug: пропуск верификации, загрузка доп. параметров…');
    equipmentPriceActionLockRef.current = true;
    setIsEquipmentPriceActionBusy(true);
    try {
      const eq = resolveEquipmentForPrice(sliderEquipmentRef.current, messages);
      const specs = resolveOrderSpecsForPrice(messages, lastOrderSpecsRef.current);
      let estimateBody =
        pendingEstimateBodyRef.current || buildEstimatePriceBody(eq, specs);
      if (!estimateBody) {
        throw new Error(
          'Не хватает id прибора на слайдере или параметров спецификации (DN, pressureMax, точность). Сначала завершите подбор расходомера.',
        );
      }
      if (isEquipmentPriceUnavailable(estimateBody.equipment)) {
        setMessages((prev) => [
          ...prev,
          {
            id: `estimate-unavailable-${Date.now()}`,
            from: 'bot',
            text: buildPriceUnavailableMessage(estimateBody.equipment),
            time: new Date(),
          },
        ]);
        return;
      }
      pendingEstimateBodyRef.current = estimateBody;

      const debugContact = {
        phone: '+7 (928) 777-77-77',
        email: 'tfdjccyi@trashlify.com',
      };
      const label = estimateBody.equipment?.name || 'оборудование';

      if (hintState.currentState === 'equipment_price_phone') {
        const chatId = await ensureChatId();
        await createMessage(chatId, {
          content: 'debug',
          hint_state: 'equipment_price_phone',
          is_hint_selection: false,
          hint_locked: true,
          debug_skip_equipment_price_verify: true,
        });
      }

      hasMessages.current = true;
      verifiedContactRef.current = debugContact;
      setAwaitingEquipmentSelection(false);
      setShowExactCostHint(false);
      setSelectedAccessoryIds([]);
      selectedAccessoriesRef.current = [];
      setHintLocked(false);
      setHintState((prev) => ({
        ...prev,
        currentState: 'order_final',
        hints: [],
        showBack: false,
        isFinal: true,
        expectsInput: false,
        hintsOnly: false,
      }));

      const tkpBody = buildTkpAccessoriesBody(estimateBody);
      if (!tkpBody) {
        throw new Error('Не удалось собрать запрос аксессуаров для выбранного прибора.');
      }
      exactCostBodyRef.current = tkpBody;
      estimateQuoteRef.current = {
        equipmentName: label,
        equipmentId: estimateBody.equipment.id,
        priceRub: null,
        priceDisplay: '',
      };

      updateTypingStage('Запрос ориентировочной цены для ТКП…');
      const quoteWithPrice = await ensureEstimateQuote();
      const priceNote =
        quoteWithPrice?.priceRub != null
          ? ` Ориентировочная цена прибора: ${quoteWithPrice.priceDisplay || `${quoteWithPrice.priceRub} ₽`}.`
          : '';

      setMessages((prev) => [
        ...prev,
        {
          id: `debug-skip-verify-${Date.now()}`,
          from: 'bot',
          text: `Верификация пропущена (debug). Выберите дополнительные параметры ниже.${priceNote}`,
          time: new Date(),
        },
      ]);

      updateTypingStage('Запрос списка аксессуаров…');
      const response = await postTkpAccessories(tkpBody);
      const accessories = Array.isArray(response.data?.accessories) ? response.data.accessories : [];
      setShowTkpPdfHint(accessories.length > 0);
      setIsSelectingAccessories(accessories.length > 0);
      setMessages((prev) => [
        ...prev,
        {
          id: `accessories-debug-${Date.now()}`,
          from: 'bot',
          kind: 'accessories',
          accessories,
          time: new Date(),
        },
      ]);
      logSelectedAccessories([], accessories);
    } catch (error) {
      console.error('[debug] пропуск верификации цены:', error);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now(),
          from: 'bot',
          text:
            error?.message ||
            'Не удалось выполнить отладочный пропуск. Нажмите «Получить цену» у карточки прибора и повторите debug.',
          time: new Date(),
        },
      ]);
    } finally {
      equipmentPriceActionLockRef.current = false;
      setIsEquipmentPriceActionBusy(false);
      endTyping();
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
        setShowTkpPdfHint(true);
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

    beginTyping('Запрос списка аксессуаров для точного расчёта…');
    try {
      const response = await postTkpAccessories(body);
      const accessories = Array.isArray(response.data?.accessories) ? response.data.accessories : [];
      setShowExactCostHint(false);
      setShowTkpPdfHint(accessories.length > 0);
      setIsSelectingAccessories(accessories.length > 0);
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
      endTyping();
    }
  };

  const handleTkpPdfHint = async () => {
    const selectedAccessories = selectedAccessoriesRef.current || [];
    const userMessage = {
      id: Date.now(),
      from: 'user',
      text: 'Получить ТКП',
      time: new Date(),
      isHint: true,
    };
    setMessages((prev) => [...prev, userMessage]);

    beginTyping('Получение цены прибора и формирование PDF ТКП…');
    let tkpDelivered = false;
    try {
      const quote = await ensureEstimateQuote();
      const body = buildTkpPdfBody(
        quote,
        selectedAccessories,
        verifiedContactRef.current,
        lastOrderSpecsRef.current,
      );

      if (!body) {
        setMessages((prev) => [
          ...prev,
          {
            id: `tkp-pdf-missing-${Date.now()}`,
            from: 'bot',
            text:
              'Не удалось сформировать ТКП: сервис не вернул цену прибора (estimate-price). Проверьте id прибора и параметры спецификации.',
            time: new Date(),
          },
        ]);
        setShowTkpPdfHint(false);
        return;
      }

      updateTypingStage('Формирование PDF ТКП на сервере…');
      const response = await postTkpPdf(body);
      const pdf = buildTkpPdfCard(response.data || {}, response.headers || {});
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
      tkpDelivered = true;
    } catch (error) {
      console.error('[tkp-pdf] ошибка:', error);
      const detail = error?.response?.data?.detail;
      let msg =
        error?.response?.data?.message ||
        error?.response?.data?.error ||
        error?.message ||
        'Ошибка сети';
      if (Array.isArray(detail) && detail.length > 0) {
        msg = detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
      }
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
      if (tkpDelivered) {
        resetAfterTkpScenario();
        await applyMainMenuHints();
      }
      endTyping();
    }
  };

  const scrollToOrderSpecsConfirm = useCallback(() => {
    requestAnimationFrame(() => {
      const el = document.querySelector('[data-order-specs-confirm="true"]');
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    });
  }, []);

  const restoreOrderSpecsConfirmInChat = useCallback(
    (preview) => {
      const rows = preview?.review_rows;
      if (!Array.isArray(rows) || rows.length === 0) return;
      const draftFromTable = orderSpecsRowsToDraft(rows);
      if (draftFromTable) {
        lastOrderSpecsRef.current = draftFromTable;
      }
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.kind === 'order_specs_confirm');
        const msg = {
          id: idx >= 0 ? prev[idx].id : `order-specs-confirm-${Date.now()}`,
          from: 'bot',
          kind: 'order_specs_confirm',
          orderSpecsTitle: preview.review_title || 'Проверьте итоговые параметры спецификации:',
          orderSpecsRows: rows,
          text: preview.footer || '',
          time: new Date(),
        };
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = msg;
          return next;
        }
        return [...prev, msg];
      });
      scrollToOrderSpecsConfirm();
    },
    [scrollToOrderSpecsConfirm],
  );

  const handleResumeFlowmeterScenario = () => {
    if (!flowmeterResume) return;

    const resumedMessage = cloneFlowmeterResumeMessage(flowmeterResume.message);
    setMessages((prev) => [
      ...prev,
      {
        id: `flowmeter-resume-user-${Date.now()}`,
        from: 'user',
        text: 'Вернуться →',
        time: new Date(),
        isHint: true,
      },
      ...(resumedMessage ? [resumedMessage] : []),
    ]);
    setHintState(flowmeterResume.hintState);
    setHintLocked(flowmeterResume.hintLocked);
    lastOrderSpecsRef.current = flowmeterResume.orderSpecs || lastOrderSpecsRef.current;
    setAwaitingEquipmentSelection(flowmeterResume.awaitingEquipmentSelection);
    setShowExactCostHint(flowmeterResume.showExactCostHint);
    setShowTkpPdfHint(flowmeterResume.showTkpPdfHint);
    setIsSelectingAccessories(flowmeterResume.isSelectingAccessories);
    setFlowmeterResume(null);
  };

  const handleBack = async () => {
    try {
      const flowmeterResumeCandidate = isFlowmeterScenario
        ? {
            hintState: {
              currentState: hintState.currentState,
              hints: hintState.hints || [],
              showBack: hintState.showBack,
              isFinal: hintState.isFinal,
              expectsInput: hintState.expectsInput,
              hintsOnly: hintState.hintsOnly,
            },
            hintLocked,
            message: findLatestFlowmeterBotMessage(messages),
            orderSpecs: lastOrderSpecsRef.current,
            awaitingEquipmentSelection,
            showExactCostHint,
            showTkpPdfHint,
            isSelectingAccessories,
          }
        : null;
      let chatIdForBack = null;
      try {
        chatIdForBack = await ensureChatId();
      } catch {
        chatIdForBack = null;
      }

      const response = await transitionHints({
        current_state: hintState.currentState,
        action: 'back',
        chat_id: chatIdForBack,
        order_specs_snapshot: lastOrderSpecsRef.current || undefined,
      });

      const newState = response.data.current_state;
      let hintsPayload = response.data;

      if (newState === 'order_specs_confirm') {
        try {
          const hintsResponse = await getHints('order_specs_confirm');
          hintsPayload = hintsResponse.data;
        } catch (e) {
          console.warn('getHints(order_specs_confirm) after back:', e);
        }
      }

      setHintState({
        currentState: newState,
        hints: hintsPayload.hints || [],
        showBack: hintsPayload.show_back ?? response.data.show_back,
        isFinal: newState === 'order_specs_confirm' ? false : hintsPayload.is_final,
        expectsInput: hintsPayload.expects_input ?? response.data.expects_input,
        hintsOnly: hintsPayload.hints_only ?? false,
      });

      if (newState === 'order_specs_confirm') {
        setHintLocked(true);
      } else if (newState === 'start' || hintsPayload.is_final) {
        setHintLocked(false);
      } else {
        setHintLocked(true);
      }

      if (FLOWMETER_HINT_STATES.has(newState)) {
        if (newState === 'order_final') {
          setAwaitingEquipmentSelection(!!lastOrderSpecsRef.current);
          setShowExactCostHint(false);
          setShowTkpPdfHint(false);
          setIsSelectingAccessories(false);
          selectedAccessoriesRef.current = [];
          setSelectedAccessoryIds([]);
        } else {
          setAwaitingEquipmentSelection(false);
          setShowExactCostHint(false);
          setShowTkpPdfHint(false);
          setIsSelectingAccessories(false);
          selectedAccessoriesRef.current = [];
          setSelectedAccessoryIds([]);
        }
      }

      if (newState === 'verification_installations') {
        gasSpuRef.current = {};
      }

      if (response.data.order_specs_json) {
        lastOrderSpecsRef.current = response.data.order_specs_json;
      }

      if (newState === 'start' && flowmeterResumeCandidate?.message) {
        setFlowmeterResume({
          ...flowmeterResumeCandidate,
          orderSpecs: response.data.order_specs_json || flowmeterResumeCandidate.orderSpecs,
        });
      } else if (newState !== 'start' || isFlowmeterScenario) {
        setFlowmeterResume(null);
      }

      if (newState === 'order_specs_confirm') {
        const preview = response.data.order_specs_preview;
        if (preview?.review_rows?.length) {
          restoreOrderSpecsConfirmInChat(preview);
        } else if (response.data.bot_message) {
          const botMsg = {
            id: Date.now(),
            from: 'bot',
            text: response.data.bot_message,
            time: new Date(),
          };
          setMessages((prev) => [...prev, enrichBotMessage(botMsg, { data: response.data })]);
        }
      } else if (response.data.bot_message && newState !== 'start') {
        const botMsg = {
          id: Date.now(),
          from: 'bot',
          text: response.data.bot_message,
          time: new Date(),
        };
        if (newState === 'verification_installations_liquid_tz' || newState === 'verification_installations_gas_application_tz') {
          botMsg.kind = 'liquid_tz_prompt';
        }
        setMessages((prev) => [...prev, enrichBotMessage(botMsg, { data: response.data })]);
      }
    } catch (error) {
      console.error('Error going back:', error);
    }
  };

  const addMessage = async (text, from = 'user', image = null, pdf = null) => {
    if (!text.trim() && !image && !pdf) return;

    const hintStepWhenSending = hintState.currentState;

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
      setFlowmeterResume(null);
      hasMessages.current = true;
      const uploadLabel = pdf
        ? hintStepWhenSending === 'order_pdf_request'
          ? 'Отправляю файл заказа на сервер (OCR или разбор DOCX и LM Studio, это может занять время)…'
          : 'Отправляю PDF на сервер…'
        : image
          ? 'Отправляю изображение на сервер…'
          : 'Отправляю сообщение на сервер…';
      beginTyping(uploadLabel);
      const pdfPipelineClientStart =
        pdf && hintStepWhenSending === 'order_pdf_request' ? performance.now() : null;
      try {
        const id = await ensureChatId();
        const msgPayload = {
          content: text.trim(),
          hint_state: hintState.currentState,
          is_hint_selection: false,
          hint_locked: hintLocked,
        };
        if (hintStepWhenSending === 'verification_installations_liquid_tz_comments' && text.trim()) {
          liquidInstallationLeadRef.current = {
            ...liquidInstallationLeadRef.current,
            tzComments: text.trim(),
          };
        }
        if (
          hintStepWhenSending === 'verification_installations_gas_application_tz_comments' &&
          text.trim()
        ) {
          gasSpuApplicationLeadRef.current = {
            ...gasSpuApplicationLeadRef.current,
            tzComments: text.trim(),
          };
        }
        if (
          hintState.currentState === 'verification_installations_liquid_contact' ||
          hintState.currentState === 'verification_installations_liquid_tz' ||
          hintState.currentState === 'verification_installations_liquid_tz_comments'
        ) {
          const r = liquidInstallationLeadRef.current;
          if (r.fullName) {
            msgPayload.liquid_installation_lead = {
              full_name: r.fullName,
              email: r.email || '',
              phone: r.phone || '',
              tz_attachment_url: r.tzAttachmentUrl || '',
              tz_file_name: r.tzFileName || '',
              tz_comments: r.tzComments || '',
            };
          }
        }
        if (
          hintState.currentState === 'verification_installations_gas_application' ||
          hintState.currentState === 'verification_installations_gas_application_contact' ||
          hintState.currentState === 'verification_installations_gas_application_tz' ||
          hintState.currentState === 'verification_installations_gas_application_tz_comments'
        ) {
          msgPayload.gas_spu_selection = { ...gasSpuRef.current };
          const rg = gasSpuApplicationLeadRef.current;
          if (rg.fullName) {
            msgPayload.gas_spu_application_lead = {
              full_name: rg.fullName,
              email: rg.email || '',
              phone: rg.phone || '',
              tz_attachment_url: rg.tzAttachmentUrl || '',
              tz_file_name: rg.tzFileName || '',
              tz_comments: rg.tzComments || '',
            };
          }
        }
        if (
          hintState.currentState === 'household_gas_fullname' ||
          hintState.currentState === 'household_gas_contact' ||
          hintState.currentState === 'household_gas_organization' ||
          hintState.currentState === 'household_gas_comment'
        ) {
          const r = householdGasLeadRef.current;
          if (Array.isArray(r.selectedItems) && r.selectedItems.length > 0) {
            msgPayload.household_gas_lead = {
              full_name: r.fullName || '',
              email: r.email || '',
              phone: r.phone || '',
              organization: r.organization || '',
              comment: r.comment || '',
              selected_items: r.selectedItems,
            };
          }
        }
        if (hintState.currentState === 'verification_installations_gas') {
          msgPayload.gas_spu_selection = { ...gasSpuRef.current };
        }
        const response = await createMessage(id, msgPayload, image, pdf);
        updateTypingStage('Ответ сервера получен, обновляю чат…');
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
            if (
              (hintStepWhenSending === 'verification_installations_liquid_tz' ||
                hintStepWhenSending === 'verification_installations_gas_application_tz') &&
              pdf &&
              userMsg.attachment_url
            ) {
              liquidTzFileRef.current = {
                file: null,
                fileName: '',
                uploadedUrl: userMsg.attachment_url,
                uploadedName: pdf.name || liquidTzFileRef.current.fileName || '',
              };
            }
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
            hintsOnly: newState.hints_only ?? false,
          });

          if (newState.current_state === 'start' || newState.is_final) {
            setHintLocked(false);
          } else if (newState.hint_locked !== undefined) {
            setHintLocked(newState.hint_locked);
          }
        }

        if (response.data.liquid_installation_lead) {
          const lead = response.data.liquid_installation_lead;
          const prev = liquidInstallationLeadRef.current;
          liquidInstallationLeadRef.current = {
            fullName: lead.full_name || prev.fullName || '',
            email: lead.email || prev.email || '',
            phone: lead.phone || prev.phone || '',
            tzAttachmentUrl: lead.tz_attachment_url || prev.tzAttachmentUrl || '',
            tzFileName: lead.tz_file_name || prev.tzFileName || '',
            tzComments:
              lead.tz_comments !== undefined && lead.tz_comments !== null
                ? String(lead.tz_comments)
                : prev.tzComments || '',
          };
        }
        if (response.data.household_gas_lead) {
          const lead = response.data.household_gas_lead;
          const prev = householdGasLeadRef.current;
          householdGasLeadRef.current = {
            fullName: lead.full_name || prev.fullName || '',
            email: lead.email || prev.email || '',
            phone: lead.phone || prev.phone || '',
            organization:
              lead.organization !== undefined && lead.organization !== null
                ? String(lead.organization)
                : prev.organization || '',
            comment:
              lead.comment !== undefined && lead.comment !== null
                ? String(lead.comment)
                : prev.comment || '',
            selectedItems: Array.isArray(lead.selected_items)
              ? lead.selected_items
              : prev.selectedItems || [],
          };
        }
        if (response.data.gas_spu_application_lead) {
          const lead = response.data.gas_spu_application_lead;
          const prev = gasSpuApplicationLeadRef.current;
          gasSpuApplicationLeadRef.current = {
            fullName: lead.full_name || prev.fullName || '',
            email: lead.email || prev.email || '',
            phone: lead.phone || prev.phone || '',
            tzAttachmentUrl: lead.tz_attachment_url || prev.tzAttachmentUrl || '',
            tzFileName: lead.tz_file_name || prev.tzFileName || '',
            tzComments:
              lead.tz_comments !== undefined && lead.tz_comments !== null
                ? String(lead.tz_comments)
                : prev.tzComments || '',
          };
        }
        logSubmitHouseholdGasResponse(response);
        logSubmitSpuApplicationResponse(response);
        if (response.data.gas_spu_selection != null) {
          gasSpuRef.current = { ...response.data.gas_spu_selection };
        }
        if (response.data.gas_spu_preview) {
          const p = response.data.gas_spu_preview;
          try {
            if (typeof console.clear === 'function') {
              console.clear();
            }
          } catch (e) {
            /* ignore */
          }
          console.log('[СПУ газ] метод запроса:', p.method);
          console.log('[СПУ газ] URL:', p.url);
          console.log('[СПУ газ] тело запроса (JSON):\n', JSON.stringify(p.body ?? {}, null, 2));
          console.log(
            '[СПУ газ] Реальный POST на URL карточки выполняется на сервере Django после кнопки «Подобрать оборудование»; в Network браузера остаётся только запрос к /api/chats/.../messages/.'
          );
        }

        if (response.data.order_specs_pipeline_timing) {
          logOrderSpecsPipelineTiming(
            response.data.order_specs_pipeline_timing,
            pdfPipelineClientStart,
          );
        }
        if (response.data.rag_llm_ms) {
          const ms = Number(response.data.rag_llm_ms) || 0;
          // eslint-disable-next-line no-console
          console.log(
            `[RAG → LM Studio] ответ получен за ${ms} ms (${(ms / 1000).toFixed(2)} с)`,
          );
        }
        if (response.data.order_specs_llm_response) {
          console.log('[ORDER_SPECS_LLM_RESPONSE]', response.data.order_specs_llm_response);
        }
        if (response.data.order_specs_ocr_text) {
          console.log('[ORDER_SPECS_OCR_TEXT]', response.data.order_specs_ocr_text);
        }

        if (isOrderFinalWithSpecs(response.data)) {
          const specs = response.data.order_specs_json;
          try {
            updateTypingStage('Подбор оборудования (GET search-equipment)…');
            const res = await fetchSearchEquipment(specs);
            const d = res.data;
            if (d?.status === 'success' && Array.isArray(d?.equipment) && d.equipment.length > 0) {
              lastOrderSpecsRef.current = specs;
              const firstItem = d.equipment[0];
              if (firstItem) sliderEquipmentRef.current = firstItem;
              setMessages((prev) => [
                ...prev,
                {
                  id: `eq-${Date.now()}`,
                  from: 'bot',
                  kind: 'equipment',
                  equipment: d.equipment,
                  orderSpecs: specs,
                  currentEquipment: firstItem || null,
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
            console.error('[search-equipment] ошибка:', err);
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
          if (botMessages.length > 0 && shouldShowOrderSpecsBotMessage(response, botMessages)) {
            const hs = response.data.hint_state;
            const firstBotMessage = botMessages[0] || {};
            const botMsg = {
              id: firstBotMessage.id,
              from: 'bot',
              text: firstBotMessage.content || '',
              time: new Date(firstBotMessage.created_at),
              ...(firstBotMessage.attachment_url ? { attachmentUrl: firstBotMessage.attachment_url } : {}),
              ...(firstBotMessage.attachment_name ? { pdfName: firstBotMessage.attachment_name } : {}),
            };
            if (
              response.data.submit_verification_liquid?.status === 'success' ||
              response.data.submit_household_gas?.status === 'success' ||
              response.data.submit_spu_application?.status === 'success'
            ) {
              botMsg.kind = 'liquid_verification_contact';
            } else if (
              hs?.current_state === 'verification_installations_liquid_tz' ||
              hs?.current_state === 'verification_installations_gas_application_tz'
            ) {
              botMsg.kind = 'liquid_tz_prompt';
            }
            setMessages((prev) => [...prev, enrichBotMessage(botMsg, response)]);
          } else if (botMessages.length > 0 && (botMessages[0].content || '').trim()) {
            const firstBotMessage = botMessages[0] || {};
            const fallbackMsg = {
              id: firstBotMessage.id,
              from: 'bot',
              text: firstBotMessage.content,
              time: new Date(firstBotMessage.created_at),
              ...(firstBotMessage.attachment_url ? { attachmentUrl: firstBotMessage.attachment_url } : {}),
              ...(firstBotMessage.attachment_name ? { pdfName: firstBotMessage.attachment_name } : {}),
            };
            setMessages((prev) => [...prev, enrichBotMessage(fallbackMsg, response)]);
          }
          if (response.data.verification_passed) {
            const contact = response.data.verified_contact || {};
            verifiedContactRef.current = {
              phone: contact.phone || '',
              email: contact.email || '',
            };
            const pendingEstimate = pendingEstimateBodyRef.current;
            const fallbackLabel = pendingEstimate?.equipment?.name || 'оборудование';
            updateTypingStage('Запрос ориентировочной цены (estimate-price)…');
            await runEstimatePrice(pendingEstimate, fallbackLabel);
          }
        }

        const applicationSubmitted =
          response.data.submit_verification_liquid?.status === 'success' ||
          response.data.submit_household_gas?.status === 'success' ||
          response.data.submit_spu_application?.status === 'success';
        if (applicationSubmitted) {
          void finishScenarioWithContactCard(id);
        }
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
        endTyping();
      }
    }
  };

  const selectOrderSpecsFile = (file) => {
    if (!file) return false;
    if (!isAllowedOrderSpecsFile(file)) {
      alert('Пожалуйста, выберите файл в формате PDF или DOCX');
      return false;
    }
    if (file.size > ORDER_SPECS_MAX_BYTES) {
      alert('Размер файла не должен превышать 15 МБ');
      return false;
    }
    setSelectedPdf(file);
    setSelectedImage(null);
    setImagePreview(null);
    return true;
  };

  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (isOrderPdfStep) {
      selectOrderSpecsFile(file);
    } else if (isLiquidTzLikeStep) {
      if (!isAllowedLiquidTzFile(file)) {
        alert('Допустимые форматы: PDF, DOC, DOCX, TXT, ZIP, RAR (до 10 МБ)');
        return;
      }
      if (file.size > LIQUID_TZ_MAX_BYTES) {
        alert('Размер файла не должен превышать 10 МБ');
        return;
      }
      setSelectedPdf(file);
      setSelectedImage(null);
      setImagePreview(null);
      liquidTzFileRef.current = {
        file,
        fileName: file.name || '',
        uploadedUrl: '',
        uploadedName: '',
      };
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

  const isOrderFileDropEnabled = isOrderPdfStep && !hintState.hintsOnly;

  const eventHasFiles = (event) =>
    Array.from(event.dataTransfer?.types || []).includes('Files');

  const handleOrderFileDragEnter = (event) => {
    if (!isOrderFileDropEnabled || !eventHasFiles(event)) return;
    event.preventDefault();
    orderFileDragDepthRef.current += 1;
    setIsOrderFileDragActive(true);
  };

  const handleOrderFileDragOver = (event) => {
    if (!isOrderFileDropEnabled || !eventHasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    setIsOrderFileDragActive(true);
  };

  const handleOrderFileDragLeave = (event) => {
    if (!isOrderFileDropEnabled || !eventHasFiles(event)) return;
    event.preventDefault();
    orderFileDragDepthRef.current = Math.max(0, orderFileDragDepthRef.current - 1);
    if (orderFileDragDepthRef.current === 0) {
      setIsOrderFileDragActive(false);
    }
  };

  const handleOrderFileDrop = (event) => {
    if (!isOrderFileDropEnabled || !eventHasFiles(event)) return;
    event.preventDefault();
    orderFileDragDepthRef.current = 0;
    setIsOrderFileDragActive(false);
    const file = event.dataTransfer?.files?.[0];
    selectOrderSpecsFile(file);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleRemoveAttachment = () => {
    setSelectedImage(null);
    setImagePreview(null);
    setSelectedPdf(null);
    if (
      hintState.currentState === 'verification_installations_liquid_tz' ||
      hintState.currentState === 'verification_installations_gas_application_tz'
    ) {
      liquidTzFileRef.current = {
        ...liquidTzFileRef.current,
        file: null,
        fileName: '',
      };
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleSend = () => {
    if (hintState.hintsOnly) return;
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
    if (hintState.hintsOnly && e.key === 'Enter') {
      e.preventDefault();
      return;
    }
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
  }, [messages, isOpen, isTyping, hintState.currentState]);

  const handleGrandGasLeaveRequest = useCallback(async (payload = {}) => {
    const selectedItems = Array.isArray(payload.selected_items) ? payload.selected_items : [];
    const selectedText = selectedItems.length
      ? `\n\nВыбранные позиции:\n${selectedItems
          .map((item) => `- ${item.name} × ${item.quantity}`)
          .join('\n')}`
      : '';
    const localMessage = {
      id: `grand-req-${Date.now()}`,
      from: 'user',
      text: `Оставить заявку на бытовой счётчик газа Гранд${selectedText}`,
      selected_items: selectedItems,
      time: new Date(),
    };
    setMessages((prev) => [...prev, localMessage]);
    hasMessages.current = true;

    const lead = {
      full_name: '',
      email: '',
      phone: '',
      organization: '',
      comment: '',
      selected_items: selectedItems,
    };
    householdGasLeadRef.current = {
      fullName: '',
      email: '',
      phone: '',
      organization: '',
      comment: '',
      selectedItems,
    };

    beginTyping('Передаю выбранные счётчики и запускаю оформление заявки…');
    try {
      const id = await ensureChatId();
      const response = await createMessage(id, {
        content: 'Оставить заявку',
        hint_state: 'equipment_household_gas_dev',
        is_hint_selection: true,
        hint_locked: hintLocked,
        household_gas_lead: lead,
      });
      updateTypingStage('Ответ сервера получен, обновляю чат…');

      if (response.data.hint_state) {
        const newState = response.data.hint_state;
        setHintState({
          currentState: newState.current_state,
          hints: newState.hints || [],
          showBack: newState.show_back,
          isFinal: newState.is_final,
          expectsInput: newState.expects_input,
          hintsOnly: newState.hints_only ?? false,
        });
        setHintLocked(newState.hint_locked !== undefined ? newState.hint_locked : true);
      }

      if (response.data.household_gas_lead) {
        const nextLead = response.data.household_gas_lead;
        householdGasLeadRef.current = {
          fullName: nextLead.full_name || '',
          email: nextLead.email || '',
          phone: nextLead.phone || '',
          organization: nextLead.organization || '',
          comment: nextLead.comment || '',
          selectedItems: Array.isArray(nextLead.selected_items) ? nextLead.selected_items : selectedItems,
        };
      }

      const botMessages = response.data.messages?.filter((msg) => !msg.is_user) || [];
      if (botMessages.length > 0) {
        const botMsg = botMessages[0];
        setMessages((prev) => [
          ...prev,
          {
            id: botMsg.id,
            from: 'bot',
            text: botMsg.content || 'Пустой ответ сервера.',
            time: new Date(botMsg.created_at),
          },
        ]);
      }
    } catch (error) {
      console.error('Error starting household gas request:', error);
      setMessages((prev) => [
        ...prev,
        {
          id: `grand-req-error-${Date.now()}`,
          from: 'bot',
          text: 'Не удалось начать оформление заявки. Попробуйте ещё раз.',
          time: new Date(),
        },
      ]);
    } finally {
      endTyping();
    }
  }, [beginTyping, ensureChatId, hintLocked, updateTypingStage]);

  return (
    <div className="chat-widget">
      <div className="chat-widget__launcher">
        {!isOpen && showGreetingTeaser ? (
          <div className="chat-widget__greeting-teaser" role="status">
            <button
              type="button"
              className="chat-widget__greeting-teaser-close"
              aria-label="Скрыть приветствие"
              onClick={() => setShowGreetingTeaser(false)}
            >
              ×
            </button>
            <button
              type="button"
              className="chat-widget__greeting-teaser-text"
              onClick={toggleOpen}
            >
              {CHAT_GREETING_TEASER_TEXT}
            </button>
          </div>
        ) : null}
        <button
          type="button"
          className={`chat-widget__toggle ${isOpen ? 'chat-widget__toggle--open' : 'chat-widget__toggle--pulse'}`}
          onClick={toggleOpen}
          aria-label="Открыть чат"
        />
      </div>

      <div
        className={`chat-widget__window ${isOpen ? 'chat-widget__window--visible' : ''}${
          isResizingChat ? ' chat-widget__window--resizing' : ''
        }${isOrderFileDropEnabled ? ' chat-widget__window--file-drop-enabled' : ''}${
          isOrderFileDragActive ? ' chat-widget__window--file-drop-active' : ''
        }`}
        style={{ height: chatWindowHeight }}
        onDragEnter={handleOrderFileDragEnter}
        onDragOver={handleOrderFileDragOver}
        onDragLeave={handleOrderFileDragLeave}
        onDrop={handleOrderFileDrop}
      >
        <div
          className="chat-widget__resize-handle"
          role="separator"
          aria-orientation="horizontal"
          aria-label="Потяните вверх или вниз, чтобы изменить высоту чата"
          onPointerDown={handleChatResizePointerDown}
        />
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
              className={`chat-widget__message chat-widget__message--${message.from}${
                message.kind === 'order_specs_confirm' ? ' chat-widget__message--order-specs-confirm' : ''
              }${
                message.kind === 'order_specs_text_clarify'
                  ? ' chat-widget__message--order-specs-clarify'
                  : ''
              }`}
              {...(message.kind === 'order_specs_confirm' ? { 'data-order-specs-confirm': 'true' } : {})}
            >
              <div
                className={`chat-widget__bubble${
                  isLiquidTzBotMessage(message) ? ' chat-widget__bubble--tz-shell' : ''
                }${
                  message.kind === 'liquid_verification_contact' ? ' chat-widget__bubble--consult-shell' : ''
                }${message.kind === 'gas_spu_card' ? ' chat-widget__bubble--gas-spu' : ''}${
                  message.kind === 'gas_spu_review' ? ' chat-widget__bubble--gas-spu-review' : ''
                }${message.kind === 'order_specs_confirm' ? ' chat-widget__bubble--order-specs-confirm' : ''}${
                  message.kind === 'order_specs_text_clarify' ? ' chat-widget__bubble--order-specs-clarify' : ''
                }`}
              >
                {message.kind === 'equipment' && message.equipment?.length ? (
                  <EquipmentShowcase
                    items={message.equipment}
                    onPick={pickEquipmentToInput}
                    onCurrentItemChange={syncSliderEquipment}
                  />
                ) : message.kind === 'order_specs_confirm' && message.orderSpecsRows?.length ? (
                  <OrderSpecsConfirmTable
                    title={message.orderSpecsTitle}
                    rows={message.orderSpecsRows}
                    footer={message.text}
                    editBusy={isTyping}
                    onEditRow={
                      hintState.currentState === 'order_specs_confirm' ? handleOrderSpecsEdit : undefined
                    }
                  />
                ) : message.kind === 'order_specs_text_clarify' && message.orderSpecsClarifyPreview ? (
                  <OrderSpecsTextClarify preview={message.orderSpecsClarifyPreview} />
                ) : message.kind === 'gas_spu_review' && message.gasSpuReviewRows?.length ? (
                  <>
                    <GasSpuReviewBlock
                      title={message.gasSpuReviewTitle}
                      rows={message.gasSpuReviewRows}
                      headingId={`gas-spu-review-h-${message.id}`}
                    />
                    {message.text ? (
                      <div className="chat-widget__gas-spu-review-footer">{message.text}</div>
                    ) : null}
                  </>
                ) : message.kind === 'gas_spu_card' && message.gasSpuCard ? (
                  <GasSpuResultCard
                    card={message.gasSpuCard}
                    specRows={message.gasSpuSpecRows}
                    leaveBusy={isTyping}
                    onLeaveRequest={
                      hintState.currentState === 'verification_installations_gas' &&
                      gasSpuRef.current?.step === 'gas_done'
                        ? () => handleHintSelect({ text: GAS_SPU_LEAVE_REQUEST })
                        : undefined
                    }
                  />
                ) : message.kind === 'accessories' && message.accessories?.length ? (
                  <AccessoriesSelector
                    items={message.accessories}
                    selectedIds={selectedAccessoryIds}
                    onToggle={handleAccessoryToggle}
                  />
                ) : message.kind === 'tkpPdf' ? (
                  <>
                    {message.text && <span className="chat-widget__message-text">{message.text}</span>}
                    <TkpPdfCard pdf={message.pdf} />
                  </>
                ) : message.kind === 'faq_card' ? (
                  <FaqCard card={message.faqCard} />
                ) : message.kind === 'liquid_verification_contact' ? (
                  <>
                    {message.text && (
                      <span className="chat-widget__liquid-consult-intro">{message.text}</span>
                    )}
                    <LiquidVerificationConsultCard />
                  </>
                ) : isLiquidTzBotMessage(message) ? (
                  <LiquidTzPromptCard templateUrl={LIQUID_TZ_QUESTIONNAIRE_URL} />
                ) : (
                  <>
                {message.text && <span className="chat-widget__message-text">{message.text}</span>}
                {(message.imageUrl || message.imagePreview) && (
                  <div className="chat-widget__image">
                    <img
                      src={message.imageUrl || message.imagePreview}
                      alt="Прикреплённое фото"
                      onClick={() => window.open(message.imageUrl || message.imagePreview, '_blank')}
                    />
                  </div>
                )}
                {message.attachmentUrl ? (
                  <AttachmentPdfCard
                    url={message.attachmentUrl}
                    filename={message.pdfName}
                    title={message.pdfName?.includes('Памятка') ? 'Скачать памятку' : 'Скачать вложение'}
                  />
                ) : message.pdfName ? (
                  <div className="chat-widget__attachment">
                    <a
                      href="#"
                      onClick={(ev) => {
                        ev.preventDefault();
                      }}
                    >
                      📎 {message.pdfName || 'Вложение'}
                    </a>
                  </div>
                ) : null}
                  </>
                )}
              </div>
              <div className="chat-widget__meta">
                <span className="chat-widget__time">{formatTime(message.time)}</span>
              </div>
            </div>
          ))}

          {hintState.currentState === 'equipment_household_gas_dev' && (
            <div className="chat-widget__message chat-widget__message--bot chat-widget__message--grand-price">
              <div className="chat-widget__bubble chat-widget__bubble--grand-price">
                <GrandGasMetersPriceBlock onLeaveRequest={handleGrandGasLeaveRequest} />
              </div>
            </div>
          )}

          {isTyping && (
            <div className="chat-widget__message chat-widget__message--bot">
              <div
                className={`chat-widget__bubble chat-widget__bubble--typing${
                  typingDetailsOpen ? ' chat-widget__bubble--typing-expanded' : ''
                }`}
              >
                <button
                  type="button"
                  className="chat-widget__typing-toggle"
                  onClick={toggleTypingDetails}
                  aria-expanded={typingDetailsOpen}
                  aria-label={
                    typingDetailsOpen ? 'Скрыть статус, показать индикатор' : 'Показать краткий статус бота'
                  }
                  title={
                    typingDetailsOpen
                      ? 'Нажмите, чтобы снова показать три точки'
                      : 'Нажмите, чтобы увидеть, что сейчас делает бот'
                  }
                >
                  {typingDetailsOpen ? (
                    <span className="chat-widget__typing-status-text">
                      {typingStage || 'Обработка…'}
                    </span>
                  ) : (
                    <span className="typing-dots" aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </span>
                  )}
                </button>
              </div>
              <div className="chat-widget__meta">
                <span className="chat-widget__time">{typingDetailsOpen ? 'статус' : 'печатает…'}</span>
              </div>
            </div>
          )}

        </div>

        <div
          className={`chat-widget__footer${
            isOrderFileDropEnabled ? ' chat-widget__footer--file-drop-enabled' : ''
          }${isOrderFileDragActive ? ' chat-widget__footer--file-drop-active' : ''}`}
        >
          {hintState.currentState === 'equipment_price_phone' && SHOW_EQUIPMENT_PRICE_DEBUG && (
            <div className="chat-widget__hints chat-widget__hints--debug">
              <button
                type="button"
                className="chat-widget__hint chat-widget__hint--debug"
                onClick={handleDebugSkipEquipmentPriceVerify}
                disabled={isEquipmentPriceActionBusy}
                title="Временно: имитирует подтверждённую почту и переход к расчёту цены. Работает только если Django settings.DEBUG = True."
              >
                debug
              </button>
            </div>
          )}
          {awaitingEquipmentSelection && (
            <div className="chat-widget__hints">
              <button
                type="button"
                className="chat-widget__hint"
                onClick={handleGetPriceHint}
                disabled={isEquipmentPriceActionBusy}
              >
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
          {isFlowmeterScenario && (
            <div className="chat-widget__hints">
              <button type="button" className="chat-widget__hint chat-widget__hint--back" onClick={handleBack}>
                ← Вернуться
              </button>
            </div>
          )}
          {footerScenarioHints.length > 0 && !awaitingEquipmentSelection && !showExactCostHint && !showTkpPdfHint && !isSelectingAccessories && (
            <div className="chat-widget__hints">
              {hintState.showBack && !isFlowmeterScenario && (
                <button type="button" className="chat-widget__hint chat-widget__hint--back" onClick={handleBack}>
                  ← Вернуться
                </button>
              )}
              {footerScenarioHints.map((hint, index) => (
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

          {hintState.showBack && !isFlowmeterScenario && (!hintState.hints || hintState.hints.length === 0) && !hintState.isFinal && !awaitingEquipmentSelection && !showExactCostHint && !showTkpPdfHint && !isSelectingAccessories && (
            <div className="chat-widget__hints">
              <button type="button" className="chat-widget__hint chat-widget__hint--back" onClick={handleBack}>
                ← Вернуться
              </button>
            </div>
          )}

          {flowmeterResume && hintState.currentState === 'start' && !awaitingEquipmentSelection && !showExactCostHint && !showTkpPdfHint && !isSelectingAccessories && (
            <div className="chat-widget__hints chat-widget__hints--resume">
              <button
                type="button"
                className="chat-widget__hint chat-widget__hint--resume"
                onClick={handleResumeFlowmeterScenario}
              >
                <span>Вернуться</span>
                <span aria-hidden="true">→</span>
              </button>
            </div>
          )}

          {isOrderFileDropEnabled && isOrderFileDragActive && (
            <div className="chat-widget__file-dropzone" aria-live="polite">
              <span className="chat-widget__file-dropzone-icon" aria-hidden="true">📎</span>
              <span>Отпустите PDF или DOCX, чтобы прикрепить файл</span>
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
              accept={fileInputAccept}
              style={{ display: 'none' }}
            />

            <button
              type="button"
              className="chat-widget__attach-btn"
              onClick={() => fileInputRef.current?.click()}
              title={attachButtonTitle}
              disabled={hintState.hintsOnly}
            >
              📎
            </button>

            <textarea
              ref={inputRef}
              className="chat-widget__input"
              rows={1}
              placeholder={
                awaitingEquipmentSelection
                  ? 'Нажмите на карточку прибора или введите сообщение...'
                  : hintState.hintsOnly
                    ? 'Выберите среду'
                    : isOrderPdfStep
                      ? 'Прикрепите PDF со спецификацией (по желанию дополните текстом)...'
                    : isLiquidTzLikeStep
                      ? 'Прикрепите файл ТЗ'
                      : isLiquidTzCommentsStep || isGasSpuApplicationTzCommentsStep
                        ? 'Комментарии к ТЗ (или «-» / «нет»)'
                        : hintState.expectsInput
                        ? 'Введите информацию...'
                        : 'Напишите сообщение...'
              }
              value={inputValue}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              disabled={hintState.hintsOnly}
              readOnly={hintState.hintsOnly}
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
