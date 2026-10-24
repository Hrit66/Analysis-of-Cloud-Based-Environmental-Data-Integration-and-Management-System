const FRAME_COUNT = 130;
const FRAME_PATH = (index) => `./frames/ezgif-frame-${String(index).padStart(3, '0')}.jpg`;
const EASING = 0.085;

const canvas = document.getElementById('sequence');
const ctx = canvas.getContext('2d', { alpha: false });

const frames = new Array(FRAME_COUNT);
const ready = new Uint8Array(FRAME_COUNT);

let progress = 0;
let targetProgress = 0;
let dirty = true;
let width = 0;
let height = 0;

function loadFrame(index) {
  const image = new Image();
  image.decoding = 'async';
  image.fetchPriority = index === 0 ? 'high' : 'low';
  image.src = FRAME_PATH(index + 1);
  image.addEventListener('load', () => {
    ready[index] = 1;
    dirty = true;
  });
  frames[index] = image;
}

for (let index = 0; index < FRAME_COUNT; index += 1) {
  loadFrame(index);
}

function nearestReady(index) {
  if (ready[index]) return index;
  for (let offset = 1; offset < FRAME_COUNT; offset += 1) {
    if (index - offset >= 0 && ready[index - offset]) return index - offset;
    if (index + offset < FRAME_COUNT && ready[index + offset]) return index + offset;
  }
  return -1;
}

function drawCover(image, alpha) {
  if (!image) return;
  const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight);
  const drawWidth = image.naturalWidth * scale;
  const drawHeight = image.naturalHeight * scale;
  const x = (width - drawWidth) / 2;
  const y = (height - drawHeight) / 2;
  ctx.globalAlpha = alpha;
  ctx.drawImage(image, x, y, drawWidth, drawHeight);
}

function render() {
  const exact = progress * (FRAME_COUNT - 1);
  const index = Math.floor(exact);
  const nextIndex = Math.min(index + 1, FRAME_COUNT - 1);
  const blend = exact - index;

  const baseIndex = nearestReady(index);
  if (baseIndex === -1) return;

  ctx.globalAlpha = 1;
  drawCover(frames[baseIndex], 1);

  if (blend > 0.001 && baseIndex === index && ready[nextIndex]) {
    drawCover(frames[nextIndex], blend);
  }

  ctx.globalAlpha = 1;
  dirty = false;
}

function resize() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  width = window.innerWidth;
  height = window.innerHeight;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  dirty = true;
  render();
}

function updateTarget() {
  const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
  targetProgress = maxScroll > 0 ? Math.min(1, Math.max(0, window.scrollY / maxScroll)) : 0;
}

function animate() {
  const difference = targetProgress - progress;

  if (Math.abs(difference) > 0.0001) {
    progress += difference * EASING;
    dirty = true;
  } else if (progress !== targetProgress) {
    progress = targetProgress;
    dirty = true;
  }

  if (dirty) render();
  requestAnimationFrame(animate);
}

window.addEventListener('scroll', updateTarget, { passive: true });
window.addEventListener('resize', resize);

resize();
updateTarget();
requestAnimationFrame(animate);
