document.addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || !input.classList.contains("file-picker-input")) {
    return;
  }

  const picker = input.closest(".file-picker");
  const name = picker?.querySelector(".file-picker-name");
  if (!name) {
    return;
  }

  name.textContent = input.files?.[0]?.name || "선택된 파일 없음";
});
