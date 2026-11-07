"use strict";
(() => {
  const dialog = document.getElementById("scanner-dialog");
  const openButton = document.getElementById("scan-open");
  if (!dialog || !openButton) return;
  const video = document.getElementById("barcode-video");
  const viewport = document.getElementById("scanner-viewport");
  const guide = document.getElementById("scanner-guide");
  const live = document.getElementById("scanner-live");
  const overlay = document.getElementById("scanner-state");
  const heading = document.getElementById("scan-state-title");
  const spinner = document.getElementById("scan-spinner");
  const stateIcon = document.getElementById("scan-state-icon");
  const status = document.getElementById("scan-status");
  const retry = document.getElementById("scan-retry");
  const photoInput = document.getElementById("barcode-photo");
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d", {willReadFrequently: true});
  let stream = null, generation = 0, pollTimer, hintTimer, submitTimer;
  let choosingPhoto = false, resumeAfterPhoto = false;

  function stop() {
    generation++;
    clearTimeout(pollTimer);
    clearTimeout(hintTimer);
    clearTimeout(submitTimer);
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null;
    video.pause();
    video.srcObject = null;
    video.hidden = true;
  }
  function state(name, text) {
    dialog.dataset.state = name;
    const active = name === "active";
    const waiting = name === "starting" || name === "photo";
    overlay.hidden = active;
    guide.hidden = !active;
    live.hidden = !active;
    spinner.hidden = !waiting;
    stateIcon.hidden = waiting;
    retry.hidden = name !== "error" || !window.isSecureContext || !navigator.mediaDevices?.getUserMedia;
    viewport.setAttribute("aria-busy", String(waiting));
    heading.textContent = name === "starting" ? gettext("Abriendo la cámara…")
      : name === "photo" ? gettext("Leyendo la foto…")
      : name === "success" ? gettext("Código leído") : gettext("Escaneo en pausa");
    status.textContent = text;
  }
  function close() {
    choosingPhoto = false;
    stop();
    if (dialog.open) dialog.close();
    document.body.classList.remove("scanner-open");
  }
  function isbn(value) {
    const code = String(value).replace(/[\s-]/g, "");
    if (!/^97[89][0-9]{10}$/.test(code)) return "";
    return [...code].reduce((total, n, i) => total + Number(n) * (i % 2 ? 3 : 1), 0) % 10 === 0 ? code : "";
  }
  function reader() {
    if (!window.ZXingBrowser?.BrowserMultiFormatOneDReader) throw new Error("DecoderUnavailable");
    return new window.ZXingBrowser.BrowserMultiFormatOneDReader();
  }
  function fail(message) {
    stop();
    state("error", message);
  }
  function detected(code) {
    stop();
    state("success", gettext("ISBN detectado: ") + code);
    submitTimer = setTimeout(() => {
      if (!dialog.open) return;
      close();
      const manual = document.getElementById("manual-isbn-form");
      if (manual) {
        document.getElementById("manual-isbn").value = code;
        manual.requestSubmit();
      } else {
        document.getElementById("catalog-query").value = code;
        document.getElementById("catalog-mode").value = "isbn";
        document.getElementById("catalog-search-form").requestSubmit();
      }
    }, 350);
  }
  function drawGuide() {
    // Crop exactly the visible guide, accounting for object-fit:cover.
    const box = viewport.getBoundingClientRect(), target = guide.getBoundingClientRect();
    if (!video.videoWidth || !video.videoHeight || !box.width || !target.width) return false;
    const scale = Math.max(box.width / video.videoWidth, box.height / video.videoHeight);
    const width = target.width / scale, height = target.height / scale;
    const x = (video.videoWidth - box.width / scale) / 2 + (target.left - box.left) / scale;
    const y = (video.videoHeight - box.height / scale) / 2 + (target.top - box.top) / scale;
    canvas.width = Math.round(Math.min(1280, width));
    canvas.height = Math.max(1, Math.round(canvas.width * height / width));
    context.drawImage(video, x, y, width, height, 0, 0, canvas.width, canvas.height);
    return true;
  }
  async function startCamera() {
    stop();
    const attempt = generation;
    state("starting", gettext("Permite el acceso a la cámara para escanear el libro."));
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      fail(gettext("La cámara necesita HTTPS o localhost. Puedes elegir una foto o escribir el ISBN."));
      return;
    }
    try {
      const decoder = reader();
      const acquired = await navigator.mediaDevices.getUserMedia({audio: false, video: {
        facingMode: {ideal: "environment"}, width: {ideal: 1920}, height: {ideal: 1080}
      }});
      // Closing during the permission prompt must not leave a camera running.
      if (attempt !== generation || !dialog.open) {
        acquired.getTracks().forEach(track => track.stop());
        return;
      }
      stream = acquired;
      video.srcObject = acquired;
      video.hidden = false;
      await video.play();
      if (attempt !== generation || !dialog.open) return;
      state("active", gettext("Se buscará el libro automáticamente al leer el código."));
      stream.getVideoTracks().forEach(track => track.addEventListener("ended", () => {
        if (attempt === generation && dialog.open) fail(gettext("La cámara se ha desconectado. Puedes volver a intentarlo."));
      }, {once: true}));
      let candidate = "", candidateAt = 0;
      const scan = () => {
        if (attempt !== generation || !dialog.open) return;
        try {
          if (video.readyState >= 2 && drawGuide()) {
            const code = isbn(decoder.decodeFromCanvas(canvas).getText());
            if (code) {
              const now = Date.now();
              // Require agreement in two frames before navigating.
              if (code === candidate && now - candidateAt < 1500) { detected(code); return; }
              candidate = code; candidateAt = now;
            } else {
              status.textContent = gettext("Apunta al código que empieza por 978 o 979.");
            }
          }
        } catch { /* No readable barcode in this frame; keep scanning. */ }
        pollTimer = setTimeout(scan, 150);
      };
      scan();
      hintTimer = setTimeout(() => {
        if (attempt === generation) status.textContent = gettext("Acerca el código al marco y evita los reflejos.");
      }, 15000);
    } catch (error) {
      if (attempt !== generation || !dialog.open) return;
      fail(error.name === "NotAllowedError" || error.name === "SecurityError"
        ? gettext("No se ha permitido la cámara. Puedes elegir una foto o escribir el ISBN.")
        : error.name === "NotFoundError" || error.name === "DevicesNotFoundError"
          ? gettext("No encontramos una cámara. Puedes usar una foto o escribir el ISBN.")
          : gettext("No hemos podido usar la cámara. Prueba una foto del código o escribe el ISBN."));
    }
  }
  openButton.addEventListener("click", () => {
    if (dialog.open) return;
    dialog.showModal();
    document.body.classList.add("scanner-open");
    startCamera();
  });
  document.getElementById("scan-close").addEventListener("click", close);
  retry.addEventListener("click", startCamera);
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  dialog.addEventListener("close", () => { stop(); document.body.classList.remove("scanner-open"); });
  dialog.addEventListener("click", event => {
    const box = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) close();
  });
  document.getElementById("scan-manual").addEventListener("click", () => {
    close();
    const field = document.getElementById("manual-isbn") || document.getElementById("catalog-query");
    const mode = document.getElementById("catalog-mode");
    if (mode) mode.value = "isbn";
    if (!isbn(field.value)) field.value = "";
    field.focus();
  });
  document.getElementById("scan-photo").addEventListener("click", () => {
    resumeAfterPhoto = dialog.dataset.state === "active";
    choosingPhoto = true;
    stop();
    state("photo", gettext("Elige una foto del código de barras."));
    photoInput.value = "";
    photoInput.click();
  });
  photoInput.addEventListener("cancel", () => {
    choosingPhoto = false;
    if (!dialog.open) return;
    if (resumeAfterPhoto) startCamera();
    else state("error", gettext("Puedes volver a usar la cámara o elegir otra foto."));
  });
  photoInput.addEventListener("change", async event => {
    choosingPhoto = false;
    const file = event.target.files[0];
    if (!file || !dialog.open) return;
    stop();
    const attempt = generation;
    if (!file.type.startsWith("image/") || file.size > 12 * 1024 * 1024) {
      fail(gettext("Elige una imagen de menos de 12 MB.")); return;
    }
    const url = URL.createObjectURL(file);
    state("photo", gettext("Leyendo el código en tu dispositivo…"));
    try {
      const result = await reader().decodeFromImageUrl(url);
      if (attempt !== generation || !dialog.open) return;
      const code = isbn(result.getText());
      if (code) detected(code);
      else fail(gettext("Ese código no es un ISBN de libro. Busca el código que empieza por 978 o 979."));
    } catch {
      if (attempt === generation && dialog.open) fail(gettext("No hemos encontrado un código legible. Prueba una foto más cercana y enfocada, o escribe el ISBN."));
    } finally { URL.revokeObjectURL(url); event.target.value = ""; }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && !choosingPhoto) close();
  });
  window.addEventListener("pagehide", close);
})();
