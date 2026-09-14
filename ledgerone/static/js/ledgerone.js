document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy-target]");
  if (!button) return;
  const target = document.querySelector(button.dataset.copyTarget);
  if (!target) return;
  try {
    await navigator.clipboard.writeText(target.value || target.textContent || "");
    const old = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = old; }, 1200);
  } catch (_) {
    if (target.select) {
      target.select();
      document.execCommand("copy");
    }
  }
});
