/* Тест: счётчик отвеченных вопросов и подтверждение перед отправкой. */
(() => {
  const form = document.getElementById("quiz-form");
  const counter = document.getElementById("quiz-counter");
  const questions = [...form.querySelectorAll("[data-question]")];

  const answered = () => questions.filter((q) => q.querySelector("input:checked")).length;

  function update() {
    counter.textContent = `Отвечено: ${answered()} из ${questions.length}`;
  }

  form.addEventListener("change", update);
  form.addEventListener("submit", (event) => {
    const missing = questions.length - answered();
    const message = missing
      ? `Без ответа осталось вопросов: ${missing}. Они будут засчитаны как неверные. Завершить тест?`
      : "Завершить тест и отправить ответы? Изменить их после отправки нельзя.";
    if (!confirm(message)) event.preventDefault();
  });
  update();
})();
