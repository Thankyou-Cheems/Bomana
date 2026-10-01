// One navigation shared by the site, calculator, flight editions and CheemsPay.
// Each build carries this module and the original Bomana icon locally.
const destinations = [
  ['home', '/'],
  ['launcher', '/launcher/'],
  ['calculator', '/calculator/'],
  ['subscription', 'https://pay.ruikang.wang/'],
  ['support', 'https://pay.ruikang.wang/contact'],
  ['docs', '/#docs'],
  ['github', 'https://github.com/Thankyou-Cheems/Bomana'],
];
const labels = {
  'zh-CN': ['首页', '启动器', '计算器', '订阅', '支持', '文档', 'GitHub', 'Bomana 全站导航', '文档与源码'],
  'zh-Hant': ['首頁', '啟動器', '計算器', '訂閱', '支援', '文件', 'GitHub', 'Bomana 全站導覽', '文件與原始碼'],
  en: ['Home', 'Launcher', 'Calculator', 'Subscribe', 'Support', 'Docs', 'GitHub', 'Bomana navigation', 'Documentation and source'],
};
const logoUrl = new URL('./bomana-app.webp', import.meta.url).href;
// Keep CSS as a same-origin file: CheemsPay's CSP intentionally rejects inline styles.
const styleUrl = new URL('./bomana-header.css?no-inline', import.meta.url).href;
const resourceIcons = [
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M12 5C9 3 5 3 2 4v15c3-1 7-1 10 1 3-2 7-2 10-1V4c-3-1-7-1-10 1Zm0 0v15"/></svg>',
  '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .9a11.1 11.1 0 0 0-3.5 21.6c.6.1.8-.2.8-.5v-2.1c-3.4.7-4.1-1.5-4.1-1.5-.6-1.4-1.3-1.8-1.3-1.8-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.7 1.3 3.4 1 .1-.8.4-1.3.7-1.6-2.7-.3-5.5-1.3-5.5-6a4.7 4.7 0 0 1 1.2-3.3c-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.4 1.3a11.7 11.7 0 0 1 6.2 0c2.4-1.6 3.4-1.3 3.4-1.3.6 1.7.2 2.9.1 3.2a4.7 4.7 0 0 1 1.2 3.3c0 4.7-2.8 5.7-5.5 6 .4.3.8 1 .8 2.1v3.4c0 .3.2.6.8.5A11.1 11.1 0 0 0 12 .9Z"/></svg>',
];

// CheemsPay also renders Shell in Node during its server-rendered UI tests.
if (typeof customElements !== 'undefined') {
  class BomanaSiteHeader extends HTMLElement {
    static observedAttributes = ['active', 'base', 'lang', 'new-tab', 'compact'];
    constructor() {
      super();
      this.attachShadow({mode:'open'});
      this.onLanguage = () => this.render();
    }
    connectedCallback() {
      this.render();
      document.addEventListener('calculator:language', this.onLanguage);
    }
    disconnectedCallback() {
      document.removeEventListener('calculator:language', this.onLanguage);
    }
    attributeChangedCallback() { if (this.isConnected) this.render(); }
    render() {
      const language = this.getAttribute('lang') || document.documentElement.lang;
      const text = labels[language] || labels['zh-CN'];
      const base = new URL(this.getAttribute('base') || 'https://bomana.ruikang.wang/', location.href);
      const compact = this.hasAttribute('compact');
      const links = destinations.map(([id, path], index) => {
        const anchor = document.createElement('a');
        anchor.href = new URL(path, base).href;
        if (index >= 5 && !compact) anchor.innerHTML = resourceIcons[index - 5];
        anchor.append(document.createTextNode(text[index]));
        if (id === this.getAttribute('active')) anchor.setAttribute('aria-current','page');
        if (this.hasAttribute('new-tab')) { anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; }
        return anchor;
      });
      this.shadowRoot.innerHTML = `<link rel="stylesheet"><header><a class="brand" aria-label="Bomana"><img alt="" width="40" height="40"><strong>BOMANA</strong></a><nav class="main-nav"></nav><nav class="resources"></nav></header>`;
      this.shadowRoot.querySelector('link').href = styleUrl;
      const brand = this.shadowRoot.querySelector('.brand');
      brand.href = base.href;
      brand.querySelector('img').src = logoUrl;
      if (this.hasAttribute('new-tab')) { brand.target = '_blank'; brand.rel = 'noopener noreferrer'; }
      const nav = this.shadowRoot.querySelector('.main-nav');
      nav.setAttribute('aria-label', text[7]);
      nav.append(...links.slice(0,compact ? 7 : 5));
      const resources = this.shadowRoot.querySelector('.resources');
      resources.setAttribute('aria-label',text[8]);
      if (!compact) resources.append(...links.slice(5));
    }
  }
  customElements.define('bomana-site-header', BomanaSiteHeader);
}
