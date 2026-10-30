(function () {
  'use strict';

  var WIDGET_ID = 'turbo-don-widget-frame';
  var TEASER_ID = 'turbo-don-widget-teaser';
  var TEASER_SEEN_KEY = 'turbo-don-widget-teaser-seen';
  var TEASER_SESSION_KEY = 'turbo-don-widget-teaser-session-hidden';
  var DEFAULT_TEASER_TEXT =
    'Здравствуйте! Помогу подобрать оборудование или ответить на ваши вопросы.';
  /* 64px кнопка + запас под пульс-кольцо без обрезки в iframe */
  var LAUNCHER_SIZE = 128;
  var LAUNCHER_GAP = 80;
  var LAUNCHER_INSET = 20;
  var DEFAULT_CHAT_WIDTH_RATIO = 0.32;
  var DEFAULT_CHAT_HEIGHT_RATIO = 0.72;
  var OFFSET_LEFT = 50;
  var OFFSET_DOWN = 20;
  var DEFAULT_WIDGET_URL = 'https://master-turbo-podbor.ru/podbor-chat/';
  var DEFAULT_IFRAME_Z_INDEX = '2147483646';
  var DEFAULT_CHAT_Z_INDEX = '2147483647';
  var DEFAULT_OPEN_HEIGHT = Math.floor(
    (Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0) || 800) *
      DEFAULT_CHAT_HEIGHT_RATIO,
  ) + LAUNCHER_GAP + LAUNCHER_INSET;
  var CHAT_WIDTH = Math.floor(
    (Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0) || 1280) *
      DEFAULT_CHAT_WIDTH_RATIO,
  ) + 38;

  if (document.getElementById(WIDGET_ID)) {
    return;
  }

  var currentScript = document.currentScript;
  if (!currentScript) {
    var widgetScripts = document.querySelectorAll('script[src*="podbor-chat/widget.js"]');
    currentScript = widgetScripts.length ? widgetScripts[widgetScripts.length - 1] : null;
  }

  function getWidgetUrl() {
    var fromAttribute = currentScript && currentScript.getAttribute('data-widget-url');
    if (fromAttribute) {
      return fromAttribute;
    }

    if (currentScript && currentScript.src) {
      try {
        return new URL('./', currentScript.src).href;
      } catch (error) {
        return DEFAULT_WIDGET_URL;
      }
    }

    return DEFAULT_WIDGET_URL;
  }

  var config = {
    url: getWidgetUrl(),
    iframeZIndex: (currentScript && currentScript.getAttribute('data-iframe-z-index')) || DEFAULT_IFRAME_Z_INDEX,
    chatZIndex: (currentScript && currentScript.getAttribute('data-z-index')) || DEFAULT_CHAT_Z_INDEX,
  };

  var iframe = document.createElement('iframe');
  iframe.id = WIDGET_ID;
  iframe.title = 'Turbo-ассистент';
  iframe.src = config.url;
  iframe.loading = 'eager';
  iframe.allow = 'clipboard-write';
  iframe.setAttribute('aria-label', 'Turbo-ассистент');
  iframe.setAttribute('allowtransparency', 'true');

  Object.assign(iframe.style, {
    position: 'fixed',
    border: '0',
    borderRadius: '0',
    margin: '0',
    padding: '0',
    background: 'transparent',
    colorScheme: 'normal',
    zIndex: config.iframeZIndex,
    overflow: 'visible',
    opacity: '1',
    pointerEvents: 'auto',
    boxSizing: 'border-box',
  });

  var teaserEl = null;
  var teaserVisible = false;
  var teaserSuppressed = false;
  var teaserFallbackTimer = null;
  var latestOpen = false;
  var latestChatFrameHeight = DEFAULT_OPEN_HEIGHT;
  var latestChatFrameWidth = CHAT_WIDTH;
  var isFrameResizing = false;
  var isShellExpanded = false;
  var frameCommitRaf = null;
  var pendingCommitOptions = null;

  function getViewport() {
    return {
      width: Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0),
      height: Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0),
    };
  }

  function getSideGutter(viewportWidth) {
    return viewportWidth <= 480 ? 12 : 24;
  }

  function getWidgetInsets(viewportWidth) {
    var sideGutter = getSideGutter(viewportWidth);
    return {
      right: sideGutter + OFFSET_LEFT,
      bottom: Math.max(0, sideGutter - OFFSET_DOWN),
    };
  }

  function clearLegacyTeaserStorage() {
    try {
      localStorage.removeItem(TEASER_SEEN_KEY);
      sessionStorage.removeItem(TEASER_SESSION_KEY);
    } catch (error) {
      /* ignore */
    }
  }

  function shouldShowTeaser() {
    return !latestOpen && !teaserSuppressed;
  }

  function suppressTeaserForPage() {
    teaserSuppressed = true;
  }

  function setLauncherPulse(_active) {
    /* Пульс только внутри iframe (CSS кнопки), не на всём фрейме — иначе обрезка и фризы */
  }

  function showDefaultTeaserIfNeeded() {
    if (!shouldShowTeaser() || teaserVisible) {
      return;
    }
    updateTeaser(true, DEFAULT_TEASER_TEXT);
    window.requestAnimationFrame(positionTeaser);
  }

  function scheduleDefaultTeaser() {
    if (!shouldShowTeaser()) {
      return;
    }
    if (teaserFallbackTimer) {
      window.clearTimeout(teaserFallbackTimer);
      teaserFallbackTimer = null;
    }
    var attempts = 0;
    function tryShow() {
      attempts += 1;
      showDefaultTeaserIfNeeded();
      if (attempts < 10 && shouldShowTeaser() && !teaserVisible) {
        teaserFallbackTimer = window.setTimeout(function () {
          teaserFallbackTimer = null;
          tryShow();
        }, 300);
      }
    }
    tryShow();
  }

  function postViewportToChild() {
    if (!iframe.contentWindow) return;
    var viewport = getViewport();
    iframe.contentWindow.postMessage(
      {
        type: 'VIEWPORT',
        width: viewport.width,
        height: viewport.height,
        widgetRight: 0,
        widgetBottom: 0,
        chatZIndex: Number(config.chatZIndex) || Number(DEFAULT_CHAT_Z_INDEX),
      },
      '*',
    );
  }

  function computeSize(isOpen, chatFrameHeight, chatFrameWidth) {
    var viewport = getViewport();
    var sideGutter = getSideGutter(viewport.width);
    var insets = getWidgetInsets(viewport.width);
    var maxWidth = Math.max(LAUNCHER_SIZE, viewport.width - insets.right - sideGutter);
    var maxFrameHeight = Math.max(LAUNCHER_SIZE, viewport.height - insets.bottom);

    if (!isOpen) {
      return {
        width: LAUNCHER_SIZE,
        height: LAUNCHER_SIZE,
        right: insets.right,
        bottom: insets.bottom,
        open: false,
      };
    }

    if (isFrameResizing && isShellExpanded) {
      return {
        width: maxWidth,
        height: maxFrameHeight,
        right: insets.right,
        bottom: insets.bottom,
        open: true,
      };
    }

    var frameHeight = Math.max(
      LAUNCHER_SIZE,
      Math.min(Number(chatFrameHeight) || DEFAULT_OPEN_HEIGHT, maxFrameHeight),
    );
    var frameWidth = Math.max(
      LAUNCHER_SIZE,
      Math.min(Number(chatFrameWidth) || latestChatFrameWidth || CHAT_WIDTH, maxWidth),
    );

    return {
      width: frameWidth,
      height: frameHeight,
      right: insets.right,
      bottom: insets.bottom,
      open: true,
    };
  }

  function commitSize(next) {
    iframe.style.width = next.width + 'px';
    iframe.style.height = next.height + 'px';
    iframe.style.right = next.right + 'px';
    iframe.style.bottom = next.bottom + 'px';
    iframe.style.left = 'auto';
    iframe.style.top = 'auto';
    iframe.style.borderRadius = next.open ? '20px' : '0';
    iframe.style.willChange = isFrameResizing ? 'width, height' : '';
    positionTeaser();
  }

  function setFrameTransitionEnabled(enabled) {
    iframe.style.transition = enabled ? 'width 180ms ease, height 180ms ease' : 'none';
  }

  function flushFrameCommit() {
    frameCommitRaf = null;
    var options = pendingCommitOptions || {};
    pendingCommitOptions = null;

    commitSize(computeSize(latestOpen, latestChatFrameHeight, latestChatFrameWidth));

    if (options.resizing) {
      return;
    }

    if (isFrameResizing) {
      isFrameResizing = false;
      isShellExpanded = false;
      setFrameTransitionEnabled(true);
    }

    if (latestOpen) {
      postViewportToChild();
    }
  }

  function scheduleFrameCommit(options) {
    pendingCommitOptions = options || {};
    if (frameCommitRaf) return;
    frameCommitRaf = window.requestAnimationFrame(flushFrameCommit);
  }

  function applyFrameState(isOpen, chatFrameHeight, chatFrameWidth, options) {
    options = options || {};
    latestOpen = Boolean(isOpen);
    if (typeof chatFrameHeight === 'number' && chatFrameHeight > 0) {
      latestChatFrameHeight = chatFrameHeight;
    }
    if (typeof chatFrameWidth === 'number' && chatFrameWidth > 0) {
      latestChatFrameWidth = chatFrameWidth;
    }

    if (options.resizing) {
      if (!isFrameResizing) {
        isFrameResizing = true;
        setFrameTransitionEnabled(false);
      }
      if (options.expandShell) {
        isShellExpanded = true;
      }
      commitSize(computeSize(latestOpen, latestChatFrameHeight, latestChatFrameWidth));
      if (options.expandShell && latestOpen) {
        postViewportToChild();
      }
      return;
    }

    isShellExpanded = false;

    if (isFrameResizing) {
      isFrameResizing = false;
      setFrameTransitionEnabled(true);
    }

    scheduleFrameCommit(options);
  }

  function ensureTeaser() {
    if (teaserEl) return teaserEl;

    teaserEl = document.createElement('div');
    teaserEl.id = TEASER_ID;
    teaserEl.setAttribute('role', 'status');
    Object.assign(teaserEl.style, {
      position: 'fixed',
      zIndex: String((Number(config.chatZIndex) || Number(DEFAULT_CHAT_Z_INDEX)) + 1),
      maxWidth: 'min(280px, calc(100vw - 140px))',
      padding: '10px 28px 10px 12px',
      borderRadius: '14px',
      background: '#ffffff',
      border: '1px solid rgba(148, 163, 184, 0.45)',
      boxShadow: '0 10px 28px rgba(15, 23, 42, 0.14)',
      fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif",
      fontSize: '13px',
      lineHeight: '1.4',
      color: '#0f172a',
      display: 'none',
      cursor: 'pointer',
      boxSizing: 'border-box',
      pointerEvents: 'auto',
    });

    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', 'Скрыть приветствие');
    closeBtn.textContent = '×';
    Object.assign(closeBtn.style, {
      position: 'absolute',
      top: '2px',
      right: '4px',
      width: '22px',
      height: '22px',
      padding: '0',
      border: 'none',
      borderRadius: '50%',
      background: 'transparent',
      color: '#94a3b8',
      fontSize: '18px',
      lineHeight: '1',
      cursor: 'pointer',
    });
    closeBtn.addEventListener('click', function (event) {
      event.stopPropagation();
      suppressTeaserForPage();
      updateTeaser(false, '');
      if (iframe.contentWindow) {
        iframe.contentWindow.postMessage({ type: 'HIDE_TEASER' }, '*');
      }
    });

    var textEl = document.createElement('span');
    textEl.className = 'turbo-don-widget-teaser__text';

    teaserEl.appendChild(closeBtn);
    teaserEl.appendChild(textEl);

    teaserEl.addEventListener('click', function () {
      applyFrameState(true, latestChatFrameHeight, latestChatFrameWidth);
      if (iframe.contentWindow) {
        iframe.contentWindow.postMessage({ type: 'OPEN_CHAT' }, '*');
      }
      updateTeaser(false, '');
    });

    document.body.appendChild(teaserEl);
    return teaserEl;
  }

  function positionTeaser() {
    if (!teaserEl || !teaserVisible) return;
    var gap = 12;
    var iframeRect = iframe.getBoundingClientRect();
    var teaserRect = teaserEl.getBoundingClientRect();
    var teaserWidth = teaserRect.width || teaserEl.offsetWidth || 240;
    var teaserHeight = teaserRect.height || teaserEl.offsetHeight || 56;
    var left = iframeRect.left - teaserWidth - gap;
    var placeAbove = left < 8;

    if (placeAbove) {
      left = Math.max(8, iframeRect.right - teaserWidth);
      teaserEl.style.left = left + 'px';
      teaserEl.style.right = 'auto';
      teaserEl.style.bottom = Math.max(8, window.innerHeight - iframeRect.top + gap) + 'px';
      teaserEl.style.top = 'auto';
      return;
    }

    teaserEl.style.left = Math.max(8, left) + 'px';
    teaserEl.style.right = 'auto';
    teaserEl.style.bottom = Math.max(0, window.innerHeight - iframeRect.bottom + 10) + 'px';
    teaserEl.style.top = 'auto';
  }

  function updateTeaser(show, text) {
    teaserVisible = Boolean(show);
    if (!teaserVisible) {
      if (teaserEl) {
        teaserEl.style.display = 'none';
      }
      if (!latestOpen) {
        setLauncherPulse(shouldShowTeaser());
      } else {
        setLauncherPulse(false);
      }
      return;
    }

    var el = ensureTeaser();
    var textNode = el.querySelector('.turbo-don-widget-teaser__text');
    if (textNode) {
      textNode.textContent = text || DEFAULT_TEASER_TEXT;
    }
    el.style.display = 'block';
    setLauncherPulse(true);
    positionTeaser();
  }

  iframe.addEventListener('load', function () {
    applyFrameState(false, latestChatFrameHeight, latestChatFrameWidth);
    postViewportToChild();
    scheduleDefaultTeaser();
    if (shouldShowTeaser()) {
      setLauncherPulse(true);
    }
  });

  window.addEventListener('message', function (event) {
    if (event.source !== iframe.contentWindow) {
      return;
    }
    var data = event.data || {};

    if (data.type === 'RESIZE') {
      var nextOpen = Boolean(data.open);
      var nextHeight = typeof data.height === 'number' ? data.height : latestChatFrameHeight;
      var nextWidth = typeof data.width === 'number' ? data.width : latestChatFrameWidth;
      applyFrameState(nextOpen, nextHeight, nextWidth, {
        resizing: data.resizing,
        expandShell: data.expandShell,
      });
      if (nextOpen) {
        updateTeaser(false, '');
      } else if (shouldShowTeaser()) {
        scheduleDefaultTeaser();
      } else if (teaserVisible) {
        window.requestAnimationFrame(positionTeaser);
      }
      return;
    }

    if (data.type === 'REQUEST_VIEWPORT') {
      postViewportToChild();
      return;
    }

    if (data.type === 'OPEN_EXTERNAL_URL' && data.url) {
      window.open(String(data.url), '_blank', 'noopener,noreferrer');
      return;
    }

    if (data.type === 'TEASER') {
      if (data.show && shouldShowTeaser()) {
        updateTeaser(true, data.text || DEFAULT_TEASER_TEXT);
        window.requestAnimationFrame(positionTeaser);
      }
    }
  });

  window.addEventListener('resize', function () {
    applyFrameState(latestOpen, latestChatFrameHeight, latestChatFrameWidth);
    if (!isFrameResizing) {
      postViewportToChild();
    }
    positionTeaser();
  });

  window.addEventListener('scroll', function () {
    positionTeaser();
  }, true);

  function mount() {
    clearLegacyTeaserStorage();
    document.body.appendChild(iframe);
    commitSize(computeSize(false, latestChatFrameHeight, latestChatFrameWidth));
    setFrameTransitionEnabled(true);
    if (shouldShowTeaser()) {
      setLauncherPulse(true);
      scheduleDefaultTeaser();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, { once: true });
  } else {
    mount();
  }
})();
