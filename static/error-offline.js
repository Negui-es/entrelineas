(() => {
  const source = document.getElementById('offline-messages');
  if (!source) return;
  const messages = JSON.parse(source.dataset.messages);
  let previous = -1;
  try { previous = Number(sessionStorage.getItem('entrelineas-outage-message') ?? -1); } catch (_) {}
  const candidates = messages.map((_, index) => index).filter(index => index !== previous);
  const selected = candidates[Math.floor(Math.random() * candidates.length)];
  document.getElementById('error-headline').textContent = messages[selected][0];
  document.getElementById('error-joke').textContent = messages[selected][1];
  try { sessionStorage.setItem('entrelineas-outage-message', selected); } catch (_) {}
})();
