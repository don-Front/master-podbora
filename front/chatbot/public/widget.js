(function () {
  'use strict';

  var WIDGET_ID = 'turbo-don-widget-frame';
  var DEFAULT_WIDGET_URL = 'https://[ТВОЙ_ДОМЕН_ХОСТИНГА]/index.html';

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
        return new URL('index.html', currentScript.src).href;
      } catch (error) {
        return DEFAULT_WIDGET_URL;
      }
    }

    return DEFAULT_WIDGET_URL;
  }

  var config = {
    url: getWidgetUrl(),
    right: (currentScript && currentScript.getAttribute('data-right')) || '24px',
    bottom: (currentScript && currentScript.getAttribute('data-bottom')) || '24px',
    zIndex: (currentScript && currentScript.getAttribute('data-z-index')) || '2147483647',
  };

  var iframe = document.createElement('iframe');
  iframe.id = WIDGET_ID;
  iframe.title = 'Turbo-don чат';
  iframe.src = config.url;
  iframe.loading = 'eager';
  iframe.allow = 'clipboard-write';
  iframe.setAttribute('aria-label', 'Turbo-don чат');

  Object.assign(iframe.style, {
    position: 'fixed',
    right: config.right,
    bottom: config.bottom,
    width: '96px',
    height: '96px',
    border: '0',
    borderRadius: '0',
    background: 'transparent',
    colorScheme: 'normal',
    zIndex: config.zIndex,
    overflow: 'hidden',
    opacity: '0',
    transition: 'width 180ms ease, height 180ms ease, opacity 180ms ease',
  });

  function viewportLimitedSize(requestedHeight) {
    var viewportWidth = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
    var viewportHeight = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
    var sideGutter = viewportWidth <= 480 ? 12 : 24;
    var height = Math.max(96, Number(requestedHeight) || 96);
    var isOpen = height > 160;

    if (!isOpen) {
      return {
        width: height > 96 ? Math.min(380, Math.max(96, viewportWidth - sideGutter * 2)) : 96,
        height: Math.min(height, Math.max(96, viewportHeight - sideGutter * 2)),
        right: sideGutter,
        bottom: sideGutter,
      };
    }

    var maxWidth = Math.max(320, viewportWidth - sideGutter * 2);
    var maxHeight = Math.max(420, viewportHeight - sideGutter * 2);

    return {
      width: Math.min(420, maxWidth),
      height: Math.min(height, maxHeight),
      right: sideGutter,
      bottom: sideGutter,
    };
  }

  var latestHeight = 96;

  function applySize(height) {
    latestHeight = Math.max(96, Number(height) || 96);
    var next = viewportLimitedSize(latestHeight);
    iframe.style.width = next.width + 'px';
    iframe.style.height = next.height + 'px';
    iframe.style.right = next.right + 'px';
    iframe.style.bottom = next.bottom + 'px';
  }

  iframe.addEventListener('load', function () {
    iframe.style.opacity = '1';
  });

  window.addEventListener('message', function (event) {
    var data = event.data || {};
    if (event.source !== iframe.contentWindow || data.type !== 'RESIZE') {
      return;
    }
    applySize(data.height);
  });

  window.addEventListener('resize', function () {
    applySize(latestHeight);
  });

  function mount() {
    document.body.appendChild(iframe);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, { once: true });
  } else {
    mount();
  }
})();
