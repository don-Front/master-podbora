const { createProxyMiddleware } = require('http-proxy-middleware');

// Django из back/chatbot (Daphne :8002). FastAPI на turbo-podbor.ru — отдельные URL в config.js.
const djangoProxyTarget = (
  process.env.REACT_APP_DJANGO_PROXY_TARGET || 'http://127.0.0.1:8002'
).replace(/\/+$/, '');

module.exports = function setupProxy(app) {
  app.use(
    '/api',
    createProxyMiddleware({
      target: djangoProxyTarget,
      changeOrigin: true,
      logLevel: 'warn',
    }),
  );
};
