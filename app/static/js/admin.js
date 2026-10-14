/* Администрирование: поиск по таблице и подтверждение необратимых действий. */
(() => {
  const filter = document.getElementById("table-filter");
  if (filter) {
    const rows = [...document.querySelectorAll("#users-table tbody tr[data-filter]")];
    filter.addEventListener("input", () => {
      const query = filter.value.trim().toLowerCase();
      for (const row of rows) row.hidden = !row.dataset.filter.includes(query);
    });
  }

  for (const form of document.querySelectorAll("form[data-confirm]")) {
    form.addEventListener("submit", (event) => {
      if (!confirm(form.dataset.confirm)) event.preventDefault();
    });
  }
})();
