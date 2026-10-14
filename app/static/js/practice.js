/* Практический урок: редактор кода, запуск в Pyodide и отправка результатов на проверку. */
(() => {
  const config = JSON.parse(document.getElementById("practice-config").textContent);
  const RUN_TIMEOUT_MS = 90_000;
  const draftKey = `cardioai:draft:${config.userId}:${config.lessonId}`;

  const statusEl = document.getElementById("runtime-status");
  const outputEl = document.getElementById("output");
  const plotsEl = document.getElementById("plots");
  const checksPanel = document.getElementById("checks-panel");
  const checksEl = document.getElementById("checks");
  const runBtn = document.getElementById("run-btn");
  const checkBtn = document.getElementById("check-btn");
  const resetBtn = document.getElementById("reset-btn");
  const nextBtn = document.getElementById("next-btn");
  const doneTag = document.getElementById("done-tag");

  function readDraft() {
    try { return localStorage.getItem(draftKey); } catch { return null; }
  }
  function writeDraft(value) {
    try { localStorage.setItem(draftKey, value); } catch { /* хранилище недоступно — не критично */ }
  }

  const editor = CodeMirror(document.getElementById("editor"), {
    value: readDraft() ?? config.saved ?? config.starter,
    mode: "python",
    lineNumbers: true,
    indentUnit: 4,
    tabSize: 4,
    indentWithTabs: false,
    matchBrackets: true,
    autoCloseBrackets: true,
    viewportMargin: Infinity,
    extraKeys: {
      "Ctrl-Enter": () => run(false),
      "Cmd-Enter": () => run(false),
      "Ctrl-/": "toggleComment",
      "Cmd-/": "toggleComment",
      Tab: (cm) => (cm.somethingSelected() ? cm.indentSelection("add") : cm.replaceSelection("    ", "end")),
      "Shift-Tab": (cm) => cm.indentSelection("subtract"),
      // Esc снимает фокус с редактора, чтобы с клавиатуры можно было уйти дальше по странице.
      Esc: (cm) => cm.getInputField().blur(),
    },
  });
  editor.getInputField().setAttribute("aria-label", "Редактор кода Python");

  let draftTimer = null;
  editor.on("change", () => {
    clearTimeout(draftTimer);
    draftTimer = setTimeout(() => writeDraft(editor.getValue()), 400);
  });

  // --- Среда выполнения ---

  let worker = null;
  let readyPromise = null;
  let pending = null;
  let runCounter = 0;

  function setStatus(state, text) {
    statusEl.dataset.state = state;
    statusEl.textContent = text;
  }

  function startWorker() {
    setStatus("loading", "Загружается среда Python…");
    worker = new Worker(config.workerUrl);
    readyPromise = new Promise((resolve, reject) => {
      worker.onmessage = (event) => {
        const message = event.data;
        if (message.type === "status") {
          setStatus("loading", message.text);
        } else if (message.type === "ready") {
          setStatus("ready", "Среда Python готова");
          resolve();
        } else if (message.type === "result" && pending && pending.id === message.id) {
          pending.resolve(message.result);
        } else if (message.type === "error") {
          if (pending && pending.id === message.id) pending.reject(new Error(message.message));
          else reject(new Error(message.message));
        }
      };
      worker.onerror = (event) => reject(new Error(event.message || "Не удалось запустить среду Python"));
    });
    worker.postMessage({
      type: "init",
      config: {
        baseUrl: config.pyodideBaseUrl,
        packages: config.packages,
        datasets: config.datasets,
        dataUrl: "/static/data/",
        harnessUrl: config.harnessUrl,
      },
    });
    return readyPromise;
  }

  function stopWorker() {
    if (worker) worker.terminate();
    worker = null;
    readyPromise = null;
  }

  async function execute(code) {
    try {
      await (readyPromise || startWorker());
    } catch (error) {
      stopWorker();
      setStatus("error", "Среда Python не загрузилась");
      throw new Error(
        `Не удалось загрузить среду Python: ${error.message}. Проверьте подключение к интернету и попробуйте ещё раз.`
      );
    }
    return new Promise((resolve, reject) => {
      const id = ++runCounter;
      const timer = setTimeout(() => {
        stopWorker();
        setStatus("idle", "Выполнение остановлено");
        reject(new Error(
          `Код выполнялся дольше ${RUN_TIMEOUT_MS / 1000} секунд и был остановлен. Проверьте, нет ли в нём бесконечного цикла.`
        ));
      }, RUN_TIMEOUT_MS);
      const finish = (callback) => (value) => { clearTimeout(timer); pending = null; callback(value); };
      pending = { id, resolve: finish(resolve), reject: finish(reject) };
      worker.postMessage({ type: "run", id, code, varNames: JSON.stringify(config.varNames) });
    });
  }

  // --- Вывод ---

  function showOutput(text, isError) {
    outputEl.textContent = text;
    outputEl.classList.toggle("is-error", Boolean(isError));
  }

  function showResult(result) {
    const parts = [];
    if (result.stdout) parts.push(result.stdout.trimEnd());
    if (result.error) parts.push(result.error);
    showOutput(parts.join("\n\n") || "Код выполнен. Вывода нет: используйте print(), чтобы увидеть значения.", result.error);
    plotsEl.replaceChildren(
      ...result.images.map((data, index) => {
        const img = document.createElement("img");
        img.src = `data:image/png;base64,${data}`;
        img.alt = `График ${index + 1}, построенный вашим кодом`;
        return img;
      })
    );
  }

  function showChecks(items, summary) {
    checksEl.replaceChildren(
      ...items.map((item) => {
        const li = document.createElement("li");
        li.className = item.ok ? "is-ok" : "is-fail";
        const mark = document.createElement("span");
        mark.textContent = item.ok ? "✓" : "✗";
        mark.setAttribute("aria-hidden", "true");
        const body = document.createElement("span");
        const label = document.createElement("span");
        label.className = "check-label";
        label.textContent = `${item.label} — ${item.ok ? "верно" : "неверно"}`;
        body.append(label);
        if (item.message) {
          const message = document.createElement("span");
          message.className = "check-message";
          message.textContent = item.message.replace(/`/g, "");
          body.append(message);
        }
        li.append(mark, body);
        return li;
      })
    );
    checksPanel.querySelector(".checks-summary")?.remove();
    if (summary) {
      const p = document.createElement("p");
      p.className = "checks-summary";
      p.textContent = summary;
      checksPanel.append(p);
    }
    checksPanel.hidden = false;
    checksPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function markDone() {
    doneTag.hidden = false;
    nextBtn.classList.remove("is-disabled");
    nextBtn.removeAttribute("aria-disabled");
    nextBtn.removeAttribute("tabindex");
  }

  // --- Действия ---

  let busy = false;
  function setBusy(value) {
    busy = value;
    runBtn.disabled = checkBtn.disabled = value;
  }

  async function submit(code, values) {
    const response = await fetch(`/api/practice/${config.lessonId}/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": config.csrfToken },
      body: JSON.stringify({ code, values }),
    });
    if (!response.ok) {
      const detail = await response.json().then((data) => data.detail, () => null);
      throw new Error(typeof detail === "string" ? detail : "Сервер не принял решение. Обновите страницу и повторите.");
    }
    return response.json();
  }

  async function run(withCheck) {
    if (busy) return;
    setBusy(true);
    const code = editor.getValue();
    writeDraft(code);
    showOutput("Выполняется…", false);
    plotsEl.replaceChildren();
    if (!withCheck) checksPanel.hidden = true;
    try {
      const result = await execute(code);
      showResult(result);
      if (!withCheck) return;
      if (result.error) {
        showChecks([], "Проверка не выполнена: сначала исправьте ошибку в коде (см. вывод программы).");
        return;
      }
      const verdict = await submit(code, result.values);
      const failed = verdict.results.filter((item) => !item.ok).length;
      showChecks(
        verdict.results,
        verdict.passed
          ? "Задание выполнено. Можно переходить дальше."
          : `Не пройдено проверок: ${failed} из ${verdict.results.length}. Исправьте код и проверьте ещё раз.`
      );
      if (verdict.passed) markDone();
    } catch (error) {
      showOutput(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  // Среда начинает загружаться сразу, пока слушатель читает условие.
  startWorker().catch(() => setStatus("error", "Среда Python не загрузилась — повторим при запуске"));

  runBtn.addEventListener("click", () => run(false));
  checkBtn.addEventListener("click", () => run(true));
  resetBtn.addEventListener("click", () => {
    if (confirm("Вернуть исходный код задания? Ваши изменения будут потеряны.")) {
      editor.setValue(config.starter);
      editor.focus();
    }
  });
})();
