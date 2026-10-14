/* Web Worker: загружает Pyodide и выполняет код слушателя вне основного потока,
   чтобы страница не зависала, а бесконечный цикл можно было прервать. */

let pyodide = null;
let ready = null;

async function init(config) {
  importScripts(config.baseUrl + "pyodide.js");
  pyodide = await loadPyodide({ indexURL: config.baseUrl });

  postMessage({ type: "status", text: "Загружаются библиотеки Python…" });
  await pyodide.loadPackage(config.packages);

  postMessage({ type: "status", text: "Загружаются данные…" });
  for (const name of config.datasets) {
    const response = await fetch(config.dataUrl + name);
    if (!response.ok) throw new Error(`Не удалось загрузить файл ${name}`);
    pyodide.FS.writeFile(name, new Uint8Array(await response.arrayBuffer()));
  }

  const harness = await fetch(config.harnessUrl);
  if (!harness.ok) throw new Error("Не удалось загрузить модуль проверки");
  pyodide.runPython(await harness.text());
}

onmessage = async (event) => {
  const message = event.data;
  try {
    if (message.type === "init") {
      ready = init(message.config);
      await ready;
      postMessage({ type: "ready" });
    } else if (message.type === "run") {
      await ready;
      const run = pyodide.globals.get("cardio_run");
      const result = JSON.parse(run(message.code, message.varNames));
      run.destroy();
      postMessage({ type: "result", id: message.id, result });
    }
  } catch (error) {
    postMessage({ type: "error", id: message.id, message: String((error && error.message) || error) });
  }
};
