(function attachSAUtils(globalObject) {
  'use strict';

  function escapeHTML(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function safeExternalURL(value, baseURL) {
    try {
      const fallbackBase = baseURL
        || (globalObject.location && globalObject.location.origin)
        || 'http://localhost';
      const url = new URL(String(value || ''), fallbackBase);
      return (url.protocol === 'http:' || url.protocol === 'https:') ? url.href : '#';
    } catch (error) {
      return '#';
    }
  }

  function formatTime(value) {
    if (!value) return '';
    const match = String(value).match(/(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2})/);
    if (!match) return String(value);
    return `${match[2]}/${match[3]} ${match[4]}`;
  }

  function formatPrice(price, currency) {
    if (price == null || !Number.isFinite(Number(price))) return '—';
    const number = Number(price);
    const normalizedCurrency = String(currency || '').toUpperCase();
    if (normalizedCurrency === 'KRW') return `₩${Math.round(number).toLocaleString('ko-KR')}`;
    if (normalizedCurrency === 'USD') return `$${number.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (normalizedCurrency === 'EUR') return `€${number.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (normalizedCurrency === 'JPY') return `¥${Math.round(number).toLocaleString('en-US')}`;
    const suffix = normalizedCurrency ? ` ${normalizedCurrency}` : '';
    return `${number.toLocaleString(undefined, { maximumFractionDigits: 4 })}${suffix}`;
  }

  function formatChangePct(value) {
    if (value == null || !Number.isFinite(Number(value))) return { text: '—', cls: 'flat' };
    const number = Number(value);
    const cls = number > 0 ? 'up' : number < 0 ? 'down' : 'flat';
    return { text: `${number > 0 ? '+' : ''}${number.toFixed(2)}%`, cls };
  }

  const api = {
    escapeHTML,
    escapeAttr: escapeHTML,
    safeExternalURL,
    formatTime,
    formatPrice,
    formatChangePct,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else globalObject.SAUtils = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
