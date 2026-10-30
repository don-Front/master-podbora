import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { postDeveloperFeedback } from '../api';

const WELCOME_TITLE = 'Обращение к разработчику';
const WELCOME_TEXT =
  'Опишите, пожалуйста, ваш вопрос или замечание по работе сервиса подбора оборудования. Сообщение будет передано команде разработки для рассмотрения.';
const SUCCESS_TEXT =
  'Спасибо. Ваше обращение принято и будет рассмотрено командой разработки.';
const SUBMIT_ERROR_TEXT =
  'Не удалось отправить обращение. Проверьте подключение к интернету и попробуйте ещё раз.';
const MAX_ATTACHMENTS = 5;
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
const ATTACHMENT_ACCEPT =
  'image/png,image/jpeg,image/jpg,application/pdf,.doc,.docx,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document';

const ALLOWED_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.pdf', '.doc', '.docx']);
const ALLOWED_MIME_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/jpg',
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]);

function getDeveloperFeedbackPageUrl() {
  try {
    if (window.parent !== window && window.parent.location?.href) {
      return window.parent.location.href;
    }
  } catch {
    /* cross-origin iframe */
  }
  const referrer = (document.referrer || '').trim();
  if (referrer) return referrer;
  return window.location.href;
}

function isValidEmail(value) {
  const email = String(value || '').trim();
  if (!email) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function getFileExtension(name) {
  const normalized = String(name || '').trim().toLowerCase();
  const dotIndex = normalized.lastIndexOf('.');
  return dotIndex >= 0 ? normalized.slice(dotIndex) : '';
}

function isAllowedDeveloperFeedbackFile(file) {
  if (!file) return false;
  const ext = getFileExtension(file.name);
  if (ALLOWED_EXTENSIONS.has(ext)) return true;
  return ALLOWED_MIME_TYPES.has(String(file.type || '').toLowerCase());
}

function isImageAttachment(file) {
  const ext = getFileExtension(file?.name);
  return ext === '.png' || ext === '.jpg' || ext === '.jpeg' || String(file?.type || '').startsWith('image/');
}

function formatFileSize(bytes) {
  const size = Number(bytes);
  if (!Number.isFinite(size) || size <= 0) return '';
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} КБ`;
  return `${(size / (1024 * 1024)).toFixed(1)} МБ`;
}

function createAttachmentEntry(file) {
  const previewUrl = isImageAttachment(file) ? URL.createObjectURL(file) : '';
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    file,
    previewUrl,
  };
}

function revokeAttachmentPreviews(items) {
  items.forEach((item) => {
    if (item?.previewUrl) {
      URL.revokeObjectURL(item.previewUrl);
    }
  });
}

function CodeBracketIcon() {
  return (
    <svg
      className="developer-contact__header-icon"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M8 7 4 12l4 5M16 7l4 5-4 5"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M10 19 14 5"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
    </svg>
  );
}

function AttachmentPreview({ attachment, onRemove, disabled }) {
  const { file, previewUrl } = attachment;
  return (
    <div className="developer-contact__attachment">
      {previewUrl ? (
        <img
          className="developer-contact__attachment-thumb"
          src={previewUrl}
          alt={file.name}
        />
      ) : (
        <div className="developer-contact__attachment-icon" aria-hidden="true">
          📎
        </div>
      )}
      <div className="developer-contact__attachment-meta">
        <span className="developer-contact__attachment-name" title={file.name}>
          {file.name}
        </span>
        <span className="developer-contact__attachment-size">{formatFileSize(file.size)}</span>
      </div>
      <button
        type="button"
        className="developer-contact__attachment-remove"
        onClick={() => onRemove(attachment.id)}
        disabled={disabled}
        aria-label={`Удалить файл ${file.name}`}
        title="Удалить файл"
      >
        ×
      </button>
    </div>
  );
}

export function DeveloperContactPanel({ onClose, isOpen = true }) {
  const panelRef = useRef(null);
  const fileInputRef = useRef(null);
  const dragDepthRef = useRef(0);
  const [fio, setFio] = useState('');
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [attachmentError, setAttachmentError] = useState('');
  const [isDragActive, setIsDragActive] = useState(false);

  const resetForm = useCallback(() => {
    setFio('');
    setEmail('');
    setMessage('');
    setAttachments((prev) => {
      revokeAttachmentPreviews(prev);
      return [];
    });
    setSubmitted(false);
    setSubmitting(false);
    setError('');
    setAttachmentError('');
    setIsDragActive(false);
    dragDepthRef.current = 0;
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  useEffect(() => {
    if (!isOpen) {
      resetForm();
    }
  }, [isOpen, resetForm]);

  const addFiles = useCallback((fileList) => {
    const incoming = Array.from(fileList || []).filter(Boolean);
    if (!incoming.length) return;

    let nextError = '';
    setAttachments((prev) => {
      const next = [...prev];
      const errors = [];

      incoming.forEach((file) => {
        if (next.length >= MAX_ATTACHMENTS) {
          errors.push(`Можно прикрепить не более ${MAX_ATTACHMENTS} файлов.`);
          return;
        }
        if (!isAllowedDeveloperFeedbackFile(file)) {
          errors.push(`Файл «${file.name}» не поддерживается. Допустимы PNG, JPG, PDF, DOC, DOCX.`);
          return;
        }
        if (file.size > MAX_ATTACHMENT_BYTES) {
          errors.push(`Файл «${file.name}» превышает 10 МБ.`);
          return;
        }
        const duplicate = next.some(
          (item) =>
            item.file.name === file.name &&
            item.file.size === file.size &&
            item.file.lastModified === file.lastModified,
        );
        if (duplicate) return;
        next.push(createAttachmentEntry(file));
      });

      if (errors.length) {
        nextError = errors[0];
      }
      return next;
    });
    setAttachmentError(nextError);
  }, []);

  const removeAttachment = useCallback((attachmentId) => {
    setAttachmentError('');
    setAttachments((prev) => {
      const target = prev.find((item) => item.id === attachmentId);
      if (target?.previewUrl) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return prev.filter((item) => item.id !== attachmentId);
    });
  }, []);

  const trimmedFio = fio.trim();
  const trimmedEmail = email.trim();
  const trimmedMessage = message.trim();
  const canSubmit = useMemo(
    () =>
      Boolean(trimmedFio && isValidEmail(trimmedEmail) && trimmedMessage) &&
      !submitting &&
      !submitted,
    [trimmedFio, trimmedEmail, trimmedMessage, submitting, submitted],
  );

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError('');
    setAttachmentError('');
    try {
      const response = await postDeveloperFeedback({
        fio: trimmedFio,
        email: trimmedEmail,
        comment: trimmedMessage,
        page_url: getDeveloperFeedbackPageUrl(),
        channel: 'web',
        files: attachments.map((item) => item.file),
      });
      if (response?.data?.status === 'success') {
        setSubmitted(true);
        return;
      }
      setError(
        String(response?.data?.message || response?.data?.detail || SUBMIT_ERROR_TEXT).trim() ||
          SUBMIT_ERROR_TEXT,
      );
    } catch (submitError) {
      const apiMessage =
        submitError?.response?.data?.message ||
        submitError?.response?.data?.detail ||
        submitError?.message;
      setError(String(apiMessage || SUBMIT_ERROR_TEXT).trim() || SUBMIT_ERROR_TEXT);
    } finally {
      setSubmitting(false);
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey && event.target.tagName === 'TEXTAREA') {
      event.preventDefault();
      handleSubmit();
    }
  };

  const handlePaste = useCallback(
    (event) => {
      if (!isOpen || submitted) return;
      const items = Array.from(event.clipboardData?.items || []);
      const pastedFiles = items
        .filter((item) => item.kind === 'file')
        .map((item) => item.getAsFile())
        .filter(Boolean);
      if (!pastedFiles.length) return;
      event.preventDefault();
      addFiles(pastedFiles);
    },
    [addFiles, isOpen, submitted],
  );

  useEffect(() => {
    if (!isOpen || submitted) return undefined;
    window.addEventListener('paste', handlePaste);
    return () => window.removeEventListener('paste', handlePaste);
  }, [handlePaste, isOpen, submitted]);

  const eventHasFiles = (event) =>
    Array.from(event.dataTransfer?.types || []).includes('Files');

  const handleDragEnter = (event) => {
    if (submitted || !eventHasFiles(event)) return;
    event.preventDefault();
    dragDepthRef.current += 1;
    setIsDragActive(true);
  };

  const handleDragOver = (event) => {
    if (submitted || !eventHasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    setIsDragActive(true);
  };

  const handleDragLeave = (event) => {
    if (submitted || !eventHasFiles(event)) return;
    event.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setIsDragActive(false);
    }
  };

  const handleDrop = (event) => {
    if (submitted || !eventHasFiles(event)) return;
    event.preventDefault();
    dragDepthRef.current = 0;
    setIsDragActive(false);
    addFiles(event.dataTransfer?.files);
  };

  const handleFileInputChange = (event) => {
    addFiles(event.target.files);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  return (
    <div
      ref={panelRef}
      className={`developer-contact${isDragActive ? ' developer-contact--drag-active' : ''}`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <header className="developer-contact__header">
        <div className="developer-contact__header-info">
          <CodeBracketIcon />
          <div>
            <div className="developer-contact__title">{WELCOME_TITLE}</div>
            <div className="developer-contact__subtitle">Сервис подбора оборудования</div>
          </div>
        </div>
        <button
          type="button"
          className="developer-contact__close"
          onClick={onClose}
          aria-label="Вернуться в чат"
        >
          ×
        </button>
      </header>

      <div className="developer-contact__body">
        {submitted ? (
          <div className="developer-contact__success" role="status" aria-live="polite">
            <div className="developer-contact__success-badge">Принято</div>
            <p className="developer-contact__success-text">{SUCCESS_TEXT}</p>
          </div>
        ) : (
          <>
            <p className="developer-contact__intro">{WELCOME_TEXT}</p>
            <div className="developer-contact__field">
              <label className="developer-contact__label" htmlFor="developer-contact-fio">
                ФИО
              </label>
              <input
                id="developer-contact-fio"
                className="developer-contact__input"
                type="text"
                value={fio}
                onChange={(event) => setFio(event.target.value)}
                placeholder="Иванов Иван Иванович"
                autoComplete="name"
                disabled={submitting}
              />
            </div>
            <div className="developer-contact__field">
              <label className="developer-contact__label" htmlFor="developer-contact-email">
                Электронная почта
              </label>
              <input
                id="developer-contact-email"
                className="developer-contact__input"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="user@company.ru"
                autoComplete="email"
                disabled={submitting}
              />
            </div>
            <div className="developer-contact__field">
              <label className="developer-contact__label" htmlFor="developer-contact-message">
                Текст обращения
              </label>
              <textarea
                id="developer-contact-message"
                className="developer-contact__textarea"
                rows={5}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Например: некорректно распознан диаметр в опросном листе…"
                disabled={submitting}
              />
            </div>

            <div className="developer-contact__attachments">
              <div className="developer-contact__attachments-head">
                <div>
                  <div className="developer-contact__attachments-title">Вложения</div>
                  <div className="developer-contact__attachments-hint">
                    PNG, JPG, PDF, DOC, DOCX · до {MAX_ATTACHMENTS} файлов · Ctrl+V для скрина
                  </div>
                </div>
                <button
                  type="button"
                  className="developer-contact__attach-btn"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={submitting || attachments.length >= MAX_ATTACHMENTS}
                  title="Прикрепить файл"
                  aria-label="Прикрепить файл"
                >
                  📎
                </button>
              </div>

              <input
                ref={fileInputRef}
                type="file"
                className="developer-contact__file-input"
                accept={ATTACHMENT_ACCEPT}
                multiple
                onChange={handleFileInputChange}
                disabled={submitting}
              />

              {attachments.length ? (
                <div className="developer-contact__attachment-list">
                  {attachments.map((attachment) => (
                    <AttachmentPreview
                      key={attachment.id}
                      attachment={attachment}
                      onRemove={removeAttachment}
                      disabled={submitting}
                    />
                  ))}
                </div>
              ) : (
                <div className="developer-contact__attachment-dropzone" aria-hidden={isDragActive}>
                  Перетащите файлы сюда или вставьте скриншот из буфера
                </div>
              )}

              {isDragActive ? (
                <div className="developer-contact__drop-overlay" aria-live="polite">
                  Отпустите файлы для прикрепления
                </div>
              ) : null}
            </div>

            {attachmentError ? (
              <p className="developer-contact__attachment-error" role="alert">
                {attachmentError}
              </p>
            ) : null}
            {error ? (
              <p className="developer-contact__error" role="alert">
                {error}
              </p>
            ) : null}
          </>
        )}
      </div>

      <footer className="developer-contact__footer">
        {submitted ? (
          <button type="button" className="developer-contact__btn developer-contact__btn--primary" onClick={onClose}>
            Вернуться в чат
          </button>
        ) : (
          <>
            <button
              type="button"
              className="developer-contact__btn developer-contact__btn--ghost"
              onClick={onClose}
              disabled={submitting}
            >
              ← Вернуться в чат
            </button>
            <button
              type="button"
              className="developer-contact__btn developer-contact__btn--primary"
              onClick={handleSubmit}
              disabled={!canSubmit}
            >
              {submitting ? 'Отправка…' : 'Отправить'}
            </button>
          </>
        )}
      </footer>
    </div>
  );
}

export function DeveloperContactIcon({
  className = 'order-specs-confirm__dev-contact-icon',
  width = 18,
  height = 18,
}) {
  return (
    <svg
      className={className}
      width={width}
      height={height}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M8 7 4 12l4 5M16 7l4 5-4 5"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M10 19 14 5"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function DeveloperContactTrigger({ onClick, disabled }) {
  return (
    <button
      type="button"
      className="order-specs-confirm__dev-contact-btn"
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick?.();
      }}
      disabled={disabled}
      title="Связаться с разработчиком"
      aria-label="Связаться с разработчиком сервиса"
    >
      <DeveloperContactIcon />
    </button>
  );
}
