(() => {
  const timerNode = document.getElementById("timer");
  const copyButton = document.getElementById("copy-link");
  let left = Number(window.__secondsLeft || 0);

  const fmt = (s) => {
    const h = Math.floor(s / 3600).toString().padStart(2, "0");
    const m = Math.floor((s % 3600) / 60).toString().padStart(2, "0");
    const sec = Math.max(0, s % 60).toString().padStart(2, "0");
    return `${h}:${m}:${sec}`;
  };

  const tick = () => {
    timerNode.textContent = `Время жизни ссылки: ${fmt(left)}`;
    left -= 1;
    if (left < 0) {
      clearInterval(int);
      timerNode.textContent = "Ссылка истекла";
    }
  };

  const int = setInterval(tick, 1000);
  tick();

  copyButton?.addEventListener("click", async () => {
    const value = copyButton.dataset.link || location.href;
    await navigator.clipboard.writeText(value);
    copyButton.textContent = "Copied";
  });
})();
