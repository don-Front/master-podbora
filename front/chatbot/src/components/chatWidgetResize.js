import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

export const MIN_CHAT_WIDTH = 280;
export const MIN_CHAT_HEIGHT = 300;
export const MAX_VIEWPORT_WIDTH_RATIO = 0.92;
/** @deprecated высота ограничивается getMaxChatHeight(), не этим коэффициентом */
export const MAX_VIEWPORT_HEIGHT_RATIO = 0.98;
export const DEFAULT_CHAT_WIDTH_RATIO = 0.32;
export const DEFAULT_CHAT_HEIGHT_RATIO = 0.72;
/** @deprecated используйте getDefaultChatWindowWidth() */
export const DEFAULT_CHAT_WINDOW_WIDTH = 342;
export const WIDGET_CONTAINER_EXTRA = 38;
export const WIDGET_LAUNCHER_GAP = 80;
export const WIDGET_LAUNCHER_INSET = 20;
/** Совпадает с `.chat-widget__panel { bottom: 80px }` */
export const CHAT_PANEL_BOTTOM_OFFSET = WIDGET_LAUNCHER_GAP;
export const CHAT_MAX_TOP_MARGIN = 8;
const CHAT_SIZE_STORAGE_KEY = 'turbo-don-chat-window-size';

let embedParentViewport = { width: null, height: null };
let lastPostedEmbedHeight = null;
let lastPostedEmbedWidth = null;
let lastPostedEmbedOpen = null;

const EMBED_RESIZE_HEIGHT_EPS = 36;
const EMBED_RESIZE_WIDTH_EPS = 20;

function readStoredChatSize() {
  try {
    const raw = localStorage.getItem(CHAT_SIZE_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const width = Number(parsed?.width);
    const height = Number(parsed?.height);
    return {
      width: Number.isFinite(width) ? width : null,
      height: Number.isFinite(height) ? height : null,
      manualWidth: Boolean(parsed?.manualWidth),
      manualHeight: Boolean(parsed?.manualHeight),
    };
  } catch {
    return null;
  }
}

function persistChatSize(width, height, manual) {
  try {
    localStorage.setItem(
      CHAT_SIZE_STORAGE_KEY,
      JSON.stringify({
        width,
        height,
        manualWidth: manual.width,
        manualHeight: manual.height,
      }),
    );
  } catch {
    /* ignore */
  }
}

export function setEmbedParentViewport(width, height) {
  const parsedWidth = Number(width);
  const parsedHeight = Number(height);
  if (Number.isFinite(parsedWidth) && parsedWidth > 0) {
    embedParentViewport.width = parsedWidth;
  }
  if (Number.isFinite(parsedHeight) && parsedHeight > 0) {
    embedParentViewport.height = parsedHeight;
  }
}

export function isWidgetEmbedded() {
  try {
    return window.parent !== window;
  } catch {
    return true;
  }
}

function getViewportSize() {
  if (isWidgetEmbedded()) {
    // В iframe innerHeight следует за размером фрейма — не использовать для clamp/max.
    return {
      width: embedParentViewport.width || 1280,
      height: embedParentViewport.height || 800,
    };
  }
  return {
    width: embedParentViewport.width || window.innerWidth || 1280,
    height: embedParentViewport.height || window.innerHeight || 800,
  };
}

export function getEmbedFrameHeight(chatWindowHeight) {
  return chatWindowHeight + WIDGET_LAUNCHER_GAP + WIDGET_LAUNCHER_INSET;
}

export function getEmbedFrameWidth(chatWindowWidth) {
  return chatWindowWidth + WIDGET_CONTAINER_EXTRA;
}

export function postEmbedResize(isOpen, chatWindowHeight, chatWindowWidth, options = {}) {
  if (!isWidgetEmbedded()) return;
  const open = Boolean(isOpen);
  const height = open ? getEmbedFrameHeight(chatWindowHeight) : undefined;
  const width = open ? getEmbedFrameWidth(chatWindowWidth) : undefined;

  if (!options.resizing && !options.force) {
    const sameOpen = lastPostedEmbedOpen === open;
    const heightCloseEnough =
      height == null
      || lastPostedEmbedHeight == null
      || Math.abs(height - lastPostedEmbedHeight) < EMBED_RESIZE_HEIGHT_EPS;
    const widthCloseEnough =
      width == null
      || lastPostedEmbedWidth == null
      || Math.abs(width - lastPostedEmbedWidth) < EMBED_RESIZE_WIDTH_EPS;
    if (sameOpen && heightCloseEnough && widthCloseEnough) {
      return;
    }
  }

  lastPostedEmbedOpen = open;
  lastPostedEmbedHeight = height ?? lastPostedEmbedHeight;
  lastPostedEmbedWidth = width ?? lastPostedEmbedWidth;

  window.parent.postMessage(
    {
      type: 'RESIZE',
      open,
      height,
      width,
      resizing: Boolean(options.resizing),
      expandShell: Boolean(options.expandShell),
    },
    '*',
  );
}

function shouldExpandEmbedShell(axis) {
  return axis === 'width' || axis === 'height' || axis === 'both';
}

function getMaxChatHeight() {
  const viewport = getViewportSize();
  const topMargin = CHAT_MAX_TOP_MARGIN;
  if (isWidgetEmbedded()) {
    const embedBottomInset = viewport.width <= 480 ? 12 : 4;
    return Math.max(
      MIN_CHAT_HEIGHT,
      Math.floor(
        viewport.height
          - embedBottomInset
          - CHAT_PANEL_BOTTOM_OFFSET
          - WIDGET_LAUNCHER_INSET
          - topMargin,
      ),
    );
  }
  const widgetBottomInset = 24;
  return Math.max(
    MIN_CHAT_HEIGHT,
    Math.floor(viewport.height - widgetBottomInset - CHAT_PANEL_BOTTOM_OFFSET - topMargin),
  );
}

function getMaxChatWidth() {
  const viewport = getViewportSize();
  const sideGutter = viewport.width <= 480 ? 12 : 24;
  if (isWidgetEmbedded()) {
    const maxFrameWidth = viewport.width - sideGutter - (sideGutter + 50);
    return Math.max(MIN_CHAT_WIDTH, Math.floor(maxFrameWidth - WIDGET_CONTAINER_EXTRA));
  }
  const maxWidth = viewport.width - sideGutter * 2 - 48;
  return Math.max(
    MIN_CHAT_WIDTH,
    Math.floor(Math.min(viewport.width * MAX_VIEWPORT_WIDTH_RATIO, maxWidth)),
  );
}

export function clampChatHeight(height) {
  const max = Math.max(getMaxChatHeight(), MIN_CHAT_HEIGHT);
  return Math.min(max, Math.max(MIN_CHAT_HEIGHT, height));
}

export function clampChatWidth(width) {
  return Math.min(getMaxChatWidth(), Math.max(MIN_CHAT_WIDTH, width));
}

export function getDefaultChatWindowWidth() {
  const viewport = getViewportSize();
  return clampChatWidth(Math.floor(viewport.width * DEFAULT_CHAT_WIDTH_RATIO));
}

export function getDefaultChatWindowHeight() {
  const viewport = getViewportSize();
  return clampChatHeight(Math.floor(viewport.height * DEFAULT_CHAT_HEIGHT_RATIO));
}

export function getInitialManualChatSizeFlags() {
  const stored = readStoredChatSize();
  return {
    width: Boolean(stored?.manualWidth),
    height: Boolean(stored?.manualHeight),
  };
}

export function getInitialChatWindowWidth() {
  const stored = readStoredChatSize();
  if (stored?.manualWidth && stored.width) {
    return clampChatWidth(stored.width);
  }
  return getDefaultChatWindowWidth();
}

export function getInitialChatWindowHeight() {
  const stored = readStoredChatSize();
  if (stored?.manualHeight && stored.height) {
    return clampChatHeight(stored.height);
  }
  return getDefaultChatWindowHeight();
}

export function applyChatWindowHeight(node, height) {
  if (!node) return;
  const clampedHeight = clampChatHeight(height);
  const px = `${clampedHeight}px`;
  const maxPx = `${Math.max(getMaxChatHeight(), MIN_CHAT_HEIGHT)}px`;
  node.style.setProperty('--chat-window-height', px);
  node.style.setProperty('--chat-window-max-height', maxPx);
  if (isWidgetEmbedded()) {
    node.style.setProperty('height', px, 'important');
    node.style.setProperty('max-height', maxPx, 'important');
  } else {
    node.style.height = px;
    node.style.maxHeight = maxPx;
  }
}

export function applyChatWindowWidth(node, width) {
  if (!node) return;
  const px = `${width}px`;
  const maxPx = `${getMaxChatWidth()}px`;
  node.style.setProperty('--chat-window-width', px);
  node.style.setProperty('--chat-window-max-width', maxPx);
  if (isWidgetEmbedded()) {
    node.style.setProperty('width', px, 'important');
    node.style.setProperty('max-width', maxPx, 'important');
  } else {
    node.style.width = px;
    node.style.maxWidth = maxPx;
  }
}

function applyChatWidgetContainerSize(containerNode, chatWindowWidth) {
  if (!containerNode) return;
  const widgetWidth = chatWindowWidth + WIDGET_CONTAINER_EXTRA;
  const px = `${widgetWidth}px`;
  const chatPx = `${chatWindowWidth}px`;
  containerNode.style.setProperty('--chat-widget-width', px);
  containerNode.style.setProperty('--chat-window-width', chatPx);
  containerNode.style.width = px;
  containerNode.style.maxWidth = px;
}

function setResizeCursor(axis) {
  document.documentElement.classList.remove(
    'chat-widget--cursor-ew',
    'chat-widget--cursor-ns',
    'chat-widget--cursor-nwse',
  );
  if (axis === 'width') {
    document.documentElement.classList.add('chat-widget--cursor-ew');
  } else if (axis === 'height') {
    document.documentElement.classList.add('chat-widget--cursor-ns');
  } else if (axis === 'both') {
    document.documentElement.classList.add('chat-widget--cursor-nwse');
  }
}

function clearResizeCursor() {
  document.documentElement.classList.remove(
    'chat-widget--cursor-ew',
    'chat-widget--cursor-ns',
    'chat-widget--cursor-nwse',
  );
}

/**
 * Ручной resize чата. При изменении ширины или высоты iframe временно разворачивается на весь viewport.
 */
export function useChatWidgetResize({
  isOpen,
  chatWindowHeight,
  setChatWindowHeight,
  chatWindowHeightRef,
  viewportVersion,
  setViewportVersion,
  chatWidgetRef,
  chatPanelRef,
  chatWindowRef,
}) {
  const [chatWindowWidth, setChatWindowWidth] = useState(getInitialChatWindowWidth);
  const chatWindowWidthRef = useRef(getInitialChatWindowWidth());
  const chatResizeDragRef = useRef(null);
  const manualChatSizeRef = useRef(getInitialManualChatSizeFlags());
  const embedResizeFrameRef = useRef(null);

  const syncChatWindowWidth = useCallback((width, options = {}) => {
    const next = clampChatWidth(width);
    chatWindowWidthRef.current = next;
    if (options.render !== false) {
      setChatWindowWidth((prev) => (prev === next ? prev : next));
    }
    return next;
  }, []);

  const scheduleEmbedResize = useCallback((resizing = false, expandShell = false) => {
    if (embedResizeFrameRef.current) return;
    embedResizeFrameRef.current = window.requestAnimationFrame(() => {
      embedResizeFrameRef.current = null;
      postEmbedResize(
        isOpen,
        chatWindowHeightRef.current,
        chatWindowWidthRef.current,
        { resizing, expandShell },
      );
    });
  }, [isOpen, chatWindowHeightRef]);

  useLayoutEffect(() => {
    if (!chatResizeDragRef.current) return;
    applyChatWindowHeight(chatPanelRef.current, chatWindowHeightRef.current);
    applyChatWindowWidth(chatPanelRef.current, chatWindowWidthRef.current);
    applyChatWidgetContainerSize(chatWidgetRef.current, chatWindowWidthRef.current);
  });

  useLayoutEffect(() => {
    if (chatResizeDragRef.current) return;
    applyChatWindowHeight(chatPanelRef.current, chatWindowHeight);
  }, [chatWindowHeight, viewportVersion, chatPanelRef]);

  useLayoutEffect(() => {
    if (chatResizeDragRef.current) return;
    const nextWidth = syncChatWindowWidth(chatWindowWidthRef.current);
    applyChatWindowWidth(chatPanelRef.current, nextWidth);
    applyChatWidgetContainerSize(chatWidgetRef.current, nextWidth);
  }, [viewportVersion, chatPanelRef, chatWidgetRef, syncChatWindowWidth]);

  useEffect(() => {
    if (chatResizeDragRef.current) return;
    if (!manualChatSizeRef.current.height) {
      setChatWindowHeight((prev) => {
        const next = getDefaultChatWindowHeight();
        chatWindowHeightRef.current = next;
        return prev === next ? prev : next;
      });
    }
    if (!manualChatSizeRef.current.width) {
      syncChatWindowWidth(getDefaultChatWindowWidth());
    } else {
      syncChatWindowWidth(chatWindowWidthRef.current);
    }
    setChatWindowHeight((prev) => clampChatHeight(prev));
  }, [viewportVersion, setChatWindowHeight, syncChatWindowWidth]);

  const finishChatResize = useCallback(() => {
    const drag = chatResizeDragRef.current;
    if (!drag) return;

    chatResizeDragRef.current = null;
    chatPanelRef.current?.classList.remove('chat-widget__panel--resizing');
    chatWindowRef.current?.classList.remove('chat-widget__window--resizing');
    document.documentElement.classList.remove('chat-widget--resizing');
    document.documentElement.classList.remove('chat-widget--shell-expanded');
    clearResizeCursor();

    if (drag.pointerId != null) {
      try {
        drag.handleEl?.releasePointerCapture?.(drag.pointerId);
      } catch {
        /* ignore */
      }
    }

    setChatWindowHeight(chatWindowHeightRef.current);
    syncChatWindowWidth(chatWindowWidthRef.current);
    persistChatSize(
      chatWindowWidthRef.current,
      chatWindowHeightRef.current,
      manualChatSizeRef.current,
    );
    postEmbedResize(
      isOpen,
      chatWindowHeightRef.current,
      chatWindowWidthRef.current,
      { resizing: false, expandShell: false },
    );
  }, [isOpen, chatPanelRef, chatWindowRef, chatWindowHeightRef, setChatWindowHeight, syncChatWindowWidth]);

  const handleChatResizePointerMove = useCallback((event) => {
    const drag = chatResizeDragRef.current;
    if (!drag || event.pointerId !== drag.pointerId) return;

    event.preventDefault();

    if (drag.pendingShellAlign) {
      drag.pendingShellAlign = false;
      drag.startX = event.clientX;
      drag.startY = event.clientY;
      drag.startWidth = chatWindowWidthRef.current;
      drag.startHeight = chatWindowHeightRef.current;
      return;
    }

    const deltaX = event.clientX - drag.startX;
    const deltaY = event.clientY - drag.startY;
    let sizeChanged = false;

    if (drag.axis === 'width' || drag.axis === 'both') {
      const nextWidth = syncChatWindowWidth(drag.startWidth - deltaX, { render: false });
      if (nextWidth !== drag.lastAppliedWidth) {
        drag.lastAppliedWidth = nextWidth;
        applyChatWindowWidth(chatPanelRef.current, nextWidth);
        applyChatWidgetContainerSize(chatWidgetRef.current, nextWidth);
        sizeChanged = true;
      }
    }

    if (drag.axis === 'height' || drag.axis === 'both') {
      const nextHeight = clampChatHeight(drag.startHeight - deltaY);
      if (nextHeight !== chatWindowHeightRef.current) {
        chatWindowHeightRef.current = nextHeight;
        applyChatWindowHeight(chatPanelRef.current, nextHeight);
        sizeChanged = true;
      }
    }

    if (sizeChanged) {
      scheduleEmbedResize(true, drag.expandShell);
    }
  }, [chatPanelRef, chatWidgetRef, chatWindowHeightRef, scheduleEmbedResize, syncChatWindowWidth]);

  const startChatResize = useCallback((event, axis) => {
    if (!isOpen) return;

    event.preventDefault();
    event.stopPropagation();

    const prevManual = manualChatSizeRef.current;
    manualChatSizeRef.current = {
      width: prevManual.width || axis === 'width' || axis === 'both',
      height: prevManual.height || axis === 'height' || axis === 'both',
    };

    const expandShell = shouldExpandEmbedShell(axis);
    const panelHeight = chatPanelRef.current?.offsetHeight || chatWindowHeightRef.current;

    chatResizeDragRef.current = {
      pointerId: event.pointerId,
      axis,
      expandShell,
      pendingShellAlign: expandShell,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: chatWindowWidthRef.current,
      startHeight: panelHeight,
      lastAppliedWidth: chatWindowWidthRef.current,
      handleEl: event.currentTarget,
    };

    chatWindowHeightRef.current = clampChatHeight(panelHeight);

    event.currentTarget.setPointerCapture(event.pointerId);
    chatPanelRef.current?.classList.add('chat-widget__panel--resizing');
    chatWindowRef.current?.classList.add('chat-widget__window--resizing');
    document.documentElement.classList.add('chat-widget--resizing');
    if (expandShell) {
      document.documentElement.classList.add('chat-widget--shell-expanded');
    }
    setResizeCursor(axis);
    applyChatWindowHeight(chatPanelRef.current, chatWindowHeightRef.current);
    applyChatWindowWidth(chatPanelRef.current, chatWindowWidthRef.current);
    applyChatWidgetContainerSize(chatWidgetRef.current, chatWindowWidthRef.current);
    postEmbedResize(
      isOpen,
      chatWindowHeightRef.current,
      chatWindowWidthRef.current,
      { resizing: true, expandShell },
    );
  }, [isOpen, chatPanelRef, chatWindowRef, chatWidgetRef, chatWindowHeightRef]);

  useEffect(() => {
    window.addEventListener('pointermove', handleChatResizePointerMove);
    window.addEventListener('pointerup', finishChatResize);
    window.addEventListener('pointercancel', finishChatResize);
    return () => {
      window.removeEventListener('pointermove', handleChatResizePointerMove);
      window.removeEventListener('pointerup', finishChatResize);
      window.removeEventListener('pointercancel', finishChatResize);
    };
  }, [finishChatResize, handleChatResizePointerMove]);

  useEffect(
    () => () => {
      if (embedResizeFrameRef.current) {
        window.cancelAnimationFrame(embedResizeFrameRef.current);
      }
    },
    [],
  );

  const handleViewportMessage = useCallback((data) => {
    const prevWidth = embedParentViewport.width;
    const prevHeight = embedParentViewport.height;
    setEmbedParentViewport(data.width, data.height);
    if (chatResizeDragRef.current) return false;
    const widthChanged = prevWidth !== embedParentViewport.width;
    const heightChanged = prevHeight !== embedParentViewport.height;
    if (!widthChanged && !heightChanged) return false;
    setViewportVersion((v) => v + 1);
    return true;
  }, [setViewportVersion]);

  const shouldSkipAutoHeightSync = useCallback(() => {
    return Boolean(chatResizeDragRef.current || manualChatSizeRef.current.height);
  }, []);

  const notifyEmbedResize = useCallback(() => {
    postEmbedResize(isOpen, chatWindowHeightRef.current, chatWindowWidthRef.current);
  }, [isOpen, chatWindowHeightRef]);

  const renderResizeHandles = () => (
    <>
      <div
        className="chat-widget__resize-handle chat-widget__resize-handle--top"
        role="separator"
        aria-orientation="horizontal"
        aria-label="Изменить высоту чата"
        onPointerDown={(event) => startChatResize(event, 'height')}
      />
      <div
        className="chat-widget__resize-handle chat-widget__resize-handle--left"
        role="separator"
        aria-orientation="vertical"
        aria-label="Изменить ширину чата"
        onPointerDown={(event) => startChatResize(event, 'width')}
      />
      <div
        className="chat-widget__resize-handle chat-widget__resize-handle--corner"
        role="presentation"
        aria-hidden="true"
        onPointerDown={(event) => startChatResize(event, 'both')}
      />
    </>
  );

  const applyDefaultChatSize = useCallback(() => {
    if (!manualChatSizeRef.current.width) {
      const nextWidth = syncChatWindowWidth(getDefaultChatWindowWidth());
      applyChatWindowWidth(chatPanelRef.current, nextWidth);
      applyChatWidgetContainerSize(chatWidgetRef.current, nextWidth);
    }
    if (!manualChatSizeRef.current.height) {
      const nextHeight = getDefaultChatWindowHeight();
      chatWindowHeightRef.current = nextHeight;
      applyChatWindowHeight(chatPanelRef.current, nextHeight);
      setChatWindowHeight(nextHeight);
    }
  }, [chatPanelRef, chatWidgetRef, chatWindowHeightRef, setChatWindowHeight, syncChatWindowWidth]);

  return {
    applyDefaultChatSize,
    chatWindowWidth,
    handleViewportMessage,
    notifyEmbedResize,
    renderResizeHandles,
    shouldSkipAutoHeightSync,
  };
}
