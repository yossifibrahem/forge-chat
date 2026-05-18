(() => {
  const api = window.lumenDesktop;
  if (!api || document.getElementById('lumen-desktop-titlebar')) {
    return;
  }

  const titlebar = document.createElement('div');
  titlebar.id = 'lumen-desktop-titlebar';
  titlebar.setAttribute('aria-label', 'Desktop title bar');
  titlebar.innerHTML = `
    <div class="lumen-titlebar-left" aria-hidden="true">
      <span class="lumen-titlebar-app-icon">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 1l2.7 7.9L23 12l-8.3 3.1L12 23l-2.7-7.9L1 12l8.3-3.1L12 1z" />
        </svg>
      </span>
    </div>
    <div class="lumen-titlebar-title" aria-hidden="true">Lumen AI Chat</div>
    <div class="lumen-titlebar-controls" aria-label="Window controls">
      <button class="lumen-titlebar-button minimize" type="button" aria-label="Minimize" title="Minimize">
        <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.25 6.75h7.5" /></svg>
      </button>
      <button class="lumen-titlebar-button maximize" type="button" aria-label="Maximize" title="Maximize">
        <svg class="maximize-icon" viewBox="0 0 12 12" aria-hidden="true"><rect x="2.5" y="2.5" width="7" height="7" rx="1.15" /></svg>
        <svg class="restore-icon" viewBox="0 0 12 12" aria-hidden="true"><path d="M4.25 2.5h5.25v5.25H7.75" /><path d="M2.5 4.25h5.25v5.25H2.5z" /></svg>
      </button>
      <button class="lumen-titlebar-button close" type="button" aria-label="Close" title="Close">
        <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3.25 3.25l5.5 5.5M8.75 3.25l-5.5 5.5" /></svg>
      </button>
    </div>
  `;
  document.body.prepend(titlebar);
  document.body.classList.add('lumen-desktop-chrome', `lumen-platform-${api.platform || 'unknown'}`);


  function parseRgb(value) {
    const probe = document.createElement('span');
    probe.style.color = value.trim();
    document.body.appendChild(probe);
    const rgb = getComputedStyle(probe).color;
    probe.remove();

    const match = rgb.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
    if (!match) {
      return null;
    }
    return {
      r: Number(match[1]),
      g: Number(match[2]),
      b: Number(match[3]),
    };
  }

  function relativeLuminance({ r, g, b }) {
    const toLinear = (channel) => {
      const value = channel / 255;
      return value <= 0.03928
        ? value / 12.92
        : ((value + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
  }

  function rgba({ r, g, b }, alpha) {
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function updateAccentTitlebarColors() {
    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue('--accent').trim() || '#cc785c';
    const accentRgb = parseRgb(accent);
    if (!accentRgb) {
      return;
    }

    const useDarkInk = relativeLuminance(accentRgb) > 0.46;
    const ink = useDarkInk ? { r: 31, g: 31, b: 30 } : { r: 255, g: 255, b: 255 };

    titlebar.style.setProperty('--desktop-titlebar-bg', accent);
    titlebar.style.setProperty('--desktop-titlebar-fg', `rgb(${ink.r}, ${ink.g}, ${ink.b})`);
    titlebar.style.setProperty('--desktop-titlebar-border', rgba(ink, useDarkInk ? 0.16 : 0.22));
    titlebar.style.setProperty('--desktop-titlebar-button-hover', rgba(ink, useDarkInk ? 0.10 : 0.16));
  }

  let accentUpdateFrame = 0;
  function scheduleAccentTitlebarUpdate() {
    cancelAnimationFrame(accentUpdateFrame);
    accentUpdateFrame = requestAnimationFrame(updateAccentTitlebarColors);
  }

  scheduleAccentTitlebarUpdate();
  new MutationObserver(scheduleAccentTitlebarUpdate).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class', 'style', 'data-theme'],
  });

  titlebar.querySelector('.minimize').addEventListener('click', () => api.minimize());
  titlebar.querySelector('.maximize').addEventListener('click', () => api.toggleMaximize());
  titlebar.querySelector('.close').addEventListener('click', () => api.close());

  api.onWindowState((state) => {
    titlebar.classList.toggle('is-maximized', Boolean(state && (state.maximized || state.fullscreen)));
  });
})();
