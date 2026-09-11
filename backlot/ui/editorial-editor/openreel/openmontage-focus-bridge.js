(() => {
  const STYLE_ID = "openmontage-viewer-focus-style";
  const CLASS_NAME = "openmontage-viewer-focus";
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    body.${CLASS_NAME} [data-testid="desktop-edit-page"] {
      position: fixed !important;
      inset: 0 !important;
      z-index: 2147483000 !important;
      grid-template-columns: 1fr !important;
      grid-template-rows: 1fr !important;
      grid-template-areas: "stage" !important;
      width: 100vw !important;
      height: 100vh !important;
    }
    body.${CLASS_NAME} [data-testid="desktop-edit-page"] > [style*="grid-area: media"],
    body.${CLASS_NAME} [data-testid="desktop-edit-page"] > [style*="grid-area: inspector"],
    body.${CLASS_NAME} [data-testid="desktop-edit-page"] > [style*="grid-area: chat"],
    body.${CLASS_NAME} [data-testid="desktop-edit-page"] > [style*="grid-area: timeline"] {
      display: none !important;
    }
  `;
  document.head.append(style);

  const savedStyles = new WeakMap();

  function findDeep(root, selector) {
    const direct = root.querySelector?.(selector);
    if (direct) return direct;
    for (const element of root.querySelectorAll?.("*") || []) {
      if (element.shadowRoot) {
        const nested = findDeep(element.shadowRoot, selector);
        if (nested) return nested;
      }
      if (element.tagName === "IFRAME" && element.contentDocument) {
        const nested = findDeep(element.contentDocument, selector);
        if (nested) return nested;
      }
    }
    return null;
  }

  function applyViewerFocus(enabled) {
    document.body.classList.toggle(CLASS_NAME, enabled);
    const grid = findDeep(document, '[data-testid="desktop-edit-page"]');
    const preview = findDeep(document, '[data-tour="preview"]')
      || findDeep(document, '[aria-label="Preview canvas"]')
      || findDeep(document, '[aria-label="画面预览"]');
    const focusRoot = preview || grid;
    if (!focusRoot) return null;
    const targets = grid ? [focusRoot, grid, ...grid.children] : [focusRoot];
    if (enabled) {
      targets.forEach((element) => {
        if (!savedStyles.has(element)) savedStyles.set(element, element.style.cssText);
      });
      [
        ["position", "fixed"], ["inset", "0"], ["z-index", "2147483000"],
        ["width", "100vw"], ["height", "100vh"],
      ].forEach(([name, value]) => focusRoot.style.setProperty(name, value, "important"));
      if (grid) [
        ["grid-template-columns", "1fr"], ["grid-template-rows", "1fr"],
        ["grid-template-areas", '"stage"'], ["width", "100vw"], ["height", "100vh"],
      ].forEach(([name, value]) => grid.style.setProperty(name, value, "important"));
      [...(grid?.children || [])].forEach((element) => {
        const area = window.getComputedStyle(element).gridArea || element.style.gridArea;
        if (["media", "inspector", "chat", "timeline"].includes(area)) {
          element.style.setProperty("display", "none", "important");
        }
      });
    } else {
      targets.forEach((element) => {
        if (savedStyles.has(element)) element.style.cssText = savedStyles.get(element);
      });
    }
    return focusRoot;
  }

  window.parent.postMessage(
    { kind: "openreel/focus-bridge-ready" },
    window.location.origin,
  );

  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    if (event.data?.kind !== "openmontage/preview-focus") return;
    const enabled = Boolean(event.data.enabled);
    const grid = applyViewerFocus(enabled);
    window.parent.postMessage(
      {
        kind: "openreel/preview-focus",
        enabled: document.body.classList.contains(CLASS_NAME),
        grid_found: Boolean(grid),
        grid_area: grid ? window.getComputedStyle(grid).gridTemplateAreas : "",
      },
      window.location.origin,
    );
  });
})();
