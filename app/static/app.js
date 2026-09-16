const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";

document.addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || !input.classList.contains("file-picker-input")) return;
  const name = input.closest("form, .file-picker, .file-drop")?.querySelector(".file-picker-name");
  if (name) name.textContent = input.files?.[0]?.name || "선택된 파일 없음";
});

document.querySelectorAll("[data-upload-form]").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const type = form.dataset.uploadType;
    const button = form.querySelector('button[type="submit"]');
    const feedback = form.querySelector(".upload-feedback");
    button.disabled = true;
    feedback.textContent = "파일을 안전하게 보관하고 처리 작업을 시작합니다…";
    try {
      const response = await fetch(`/api/upload-batches/${type}`, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-CSRF-Token": csrfToken },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "업로드를 시작하지 못했습니다.");
      window.location.assign(`/batches/${payload.batch_id}`);
    } catch (error) {
      feedback.textContent = error.message;
      feedback.classList.add("error-text");
      button.disabled = false;
    }
  });
});

document.querySelectorAll("[data-direct-match-form]").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    const feedback = form.querySelector(".upload-feedback");
    button.disabled = true;
    feedback.textContent = "두 파일을 검증하고 Part Number FIFO allocation을 계산합니다…";
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: {
          Accept: "application/json",
          "X-CSRF-Token": csrfToken,
        },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "매칭을 실행하지 못했습니다.");
      window.location.assign(payload.redirect_url);
    } catch (error) {
      feedback.textContent = error.message;
      feedback.classList.add("error-text");
      button.disabled = false;
    }
  });
});

const pollingPanel = document.querySelector("[data-batch-poll]");
if (pollingPanel) {
  const batchId = pollingPanel.dataset.batchPoll;
  const counter = pollingPanel.querySelector("[data-progress-count]");
  const intervalId = setInterval(async () => {
    try {
      const response = await fetch(`/api/upload-batches/${batchId}`);
      if (!response.ok) return;
      const payload = await response.json();
      if (counter) counter.textContent = payload.processed_rows;
      if (["review_ready", "failed", "confirmed"].includes(payload.status)) {
        clearInterval(intervalId);
        window.location.reload();
      }
    } catch (_) {
      // A transient network error is retried on the next interval.
    }
  }, 1500);
}
