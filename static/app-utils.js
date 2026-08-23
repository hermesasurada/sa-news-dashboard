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

  function formatExtendedMarketState(value, fallbackLabel) {
    const state = String(value || '').trim().toUpperCase();
    if (state.startsWith('PRE')) return 'PRE';
    if (state.includes('POST')) return 'POST';
    return String(fallbackLabel || '').trim() || '장외';
  }

  function isExtendedMarketState(value) {
    const state = String(value || '').trim().toUpperCase();
    return state.startsWith('PRE') || state.includes('POST');
  }

  function formatSummaryModel(value) {
    const model = String(value || '');
    if (!model) return '';
    const claude = model.match(/^claude-(opus|sonnet|haiku)-(\d+)(?:-(\d{1,2}))?(?:-|$)/i);
    if (claude) {
      const family = claude[1][0].toUpperCase() + claude[1].slice(1).toLowerCase();
      const version = claude[3] ? `${claude[2]}.${claude[3]}` : claude[2];
      return `Claude ${family} ${version}`;
    }
    if (model.startsWith('claude')) return 'Claude';
    const grok = model.match(/^grok-([\d.]+)/);
    if (grok) return `Grok ${grok[1]}`;
    if (model.startsWith('grok')) return 'Grok';
    return model;
  }

  const api = {
    escapeHTML,
    escapeAttr: escapeHTML,
    safeExternalURL,
    formatTime,
    formatPrice,
    formatChangePct,
    formatExtendedMarketState,
    isExtendedMarketState,
    formatSummaryModel,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else globalObject.SAUtils = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
