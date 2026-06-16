(function () {
  'use strict';

  var WIDGET_ID = 'turbo-don-widget-frame';
  var TEASER_ID = 'turbo-don-widget-teaser';
  var LAUNCHER_SIZE = 112;
  var CHAT_WIDTH = 380;
  var LAUNCHER_GAP = 80;
  var LAUNCHER_INSET = 20;
  var DEFAULT_OPEN_HEIGHT = 300 + LAUNCHER_GAP + LAUNCHER_INSET;
  var OFFSET_LEFT = 50;
  var OFFSET_DOWN = 20;
  var DEFAULT_WIDGET_URL = 'https://turbo-podbor.ru/podbor-chat/';

  if (document.getElementById(WIDGET_ID)) {
    return;
  }

  var currentScript = document.currentScript;

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
    right: (currentScript && currentScript.getAttribute('data-right')) || '74px',
    bottom: (currentScript && currentScript.getAttribute('data-bottom')) || '4px',
    zIndex: (currentScript && currentScript.getAttribute('data-z-index')) || '2147483647',
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
    right: config.right,
    bottom: config.bottom,
    width: LAUNCHER_SIZE + 'px',
    height: LAUNCHER_SIZE + 'px',
    border: '0',
    borderRadius: '0',
    background: 'transparent',
    colorScheme: 'normal',
    zIndex: config.zIndex,
    overflow: 'hidden',
    opacity: '0',
    pointerEvents: 'auto',
    transition: 'width 180ms ease, opacity 180ms ease',
  });

  var teaserEl = null;
  var teaserVisible = false;
  var latestOpen = false;
  var latestChatFrameHeight = DEFAULT_OPEN_HEIGHT;

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

  function postViewportToChild() {
    if (!iframe.contentWindow) return;
    var viewport = getViewport();
    iframe.contentWindow.postMessage(
      {
        type: 'VIEWPORT',
        width: viewport.width,
        height: viewport.height,
      },
      '*',
    );
  }

  function computeSize(isOpen, chatFrameHeight) {
    var viewport = getViewport();
    var sideGutter = getSideGutter(viewport.width);
    var insets = getWidgetInsets(viewport.width);

    if (!isOpen) {
      return {
        width: LAUNCHER_SIZE,
        height: LAUNCHER_SIZE,
        right: insets.right,
        bottom: insets.bottom,
        open: false,
      };
    }

    var maxWidth = Math.max(LAUNCHER_SIZE, viewport.width - insets.right - sideGutter);
    var maxFrameHeight = Math.max(LAUNCHER_SIZE, viewport.height - insets.bottom);
    var frameHeight = Math.max(
      LAUNCHER_SIZE,
      Math.min(Number(chatFrameHeight) || DEFAULT_OPEN_HEIGHT, maxFrameHeight),
    );

    return {
      width: Math.min(CHAT_WIDTH, maxWidth),
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
    positionTeaser();
  }

  function applyFrameState(isOpen, chatFrameHeight) {
    latestOpen = Boolean(isOpen);
    if (typeof chatFrameHeight === 'number' && chatFrameHeight > 0) {
      latestChatFrameHeight = chatFrameHeight;
    }
    commitSize(computeSize(latestOpen, latestChatFrameHeight));
    if (latestOpen) {
      postViewportToChild();
    }
  }

  function ensureTeaser() {
    if (teaserEl) return teaserEl;

    teaserEl = document.createElement('div');
    teaserEl.id = TEASER_ID;
    teaserEl.setAttribute('role', 'status');
    Object.assign(teaserEl.style, {
      position: 'fixed',
      zIndex: String(Number(config.zIndex) + 1),
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
      applyFrameState(true, latestChatFrameHeight);
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
    var teaserRect = teaserEl.getBoundingClientRect();
    var gap = 12;
    var viewport = getViewport();
    var insets = getWidgetInsets(viewport.width);
    var launcherLeft = viewport.width - insets.right - LAUNCHER_SIZE;
    var left = launcherLeft - teaserRect.width - gap;
    var bottom = insets.bottom + 10;

    if (left < 8) {
      left = 8;
    }

    teaserEl.style.left = left + 'px';
    teaserEl.style.right = 'auto';
    teaserEl.style.bottom = bottom + 'px';
    teaserEl.style.top = 'auto';
  }

  function updateTeaser(show, text) {
    teaserVisible = Boolean(show);
    if (!teaserVisible) {
      if (teaserEl) {
        teaserEl.style.display = 'none';
      }
      return;
    }

    var el = ensureTeaser();
    var textNode = el.querySelector('.turbo-don-widget-teaser__text');
    if (textNode) {
      textNode.textContent = text || '';
    }
    el.style.display = 'block';
    positionTeaser();
  }

  iframe.addEventListener('load', function () {
    iframe.style.opacity = '1';
    postViewportToChild();
  });

  window.addEventListener('message', function (event) {
    if (event.source !== iframe.contentWindow) {
      return;
    }
    var data = event.data || {};

    if (data.type === 'RESIZE') {
      var nextOpen = Boolean(data.open);
      var nextHeight = typeof data.height === 'number' ? data.height : latestChatFrameHeight;
      applyFrameState(nextOpen, nextHeight);
      if (nextOpen) {
        updateTeaser(false, '');
      } else if (teaserVisible) {
        window.requestAnimationFrame(positionTeaser);
      }
      return;
    }

    if (data.type === 'REQUEST_VIEWPORT') {
      postViewportToChild();
      return;
    }

    if (data.type === 'TEASER') {
      updateTeaser(data.show, data.text);
      if (data.show) {
        window.requestAnimationFrame(positionTeaser);
      }
    }
  });

  window.addEventListener('resize', function () {
    applyFrameState(latestOpen, latestChatFrameHeight);
    postViewportToChild();
  });

  window.addEventListener('scroll', function () {
    positionTeaser();
  }, true);

  function mount() {
    document.body.appendChild(iframe);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, { once: true });
  } else {
    mount();
  }
})();
