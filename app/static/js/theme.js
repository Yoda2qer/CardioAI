/* Тема оформления. Подключается в <head> без defer, чтобы тема применилась до отрисовки
   страницы и не было вспышки светлого фона. Выбор пользователя хранится в localStorage,
   без него действует настройка системы. */
(() => {
  const KEY = "cardioai:theme";
  const root = document.documentElement;
  const media = window.matchMedia("(prefers-color-scheme: dark)");

  function stored() {
    try { return localStorage.getItem(KEY); } catch { return null; }
  }

  function syncButtons() {
    const dark = root.dataset.theme === "dark";
    for (const button of document.querySelectorAll("[data-theme-toggle]")) {
      button.setAttribute("aria-pressed", String(dark));
      button.title = dark ? "Светлая тема" : "Тёмная тема";
    }
  }

  function apply() {
    root.dataset.theme = stored() || (media.matches ? "dark" : "light");
    syncButtons();
  }

  apply();
  media.addEventListener("change", apply);
  document.addEventListener("DOMContentLoaded", syncButtons);
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-theme-toggle]");
    if (!button) return;
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem(KEY, next); } catch { /* без сохранения выбор действует до перезагрузки */ }
    root.dataset.theme = next;
    syncButtons();
  });
})();
