import * as PIXI from 'pixi.js';
import { Animator } from './anim/animator';
import { SpeechPlayer } from './anim/speech';
import { DesktopGaze } from './companion/desktopGaze';
import { Director } from './companion/director';
import { drawablesUnderPart, filterDrawables, loadRig } from './live2d';
import { MirrorArm } from './mirrorArm';
import { buildPanel } from './ui';

const MODEL_URL = '/model/deepseek/deepseek.model3.json';
// The rig's right "index finger up" posed arm (Movement3).
const POINTING_ARM = 'Part54';

export type ViewName = 'full' | 'upper' | 'face';
// Normalized model point placed at screen center, and zoom relative to "fit whole body".
const VIEWS: Record<ViewName, { zoom: number; fx: number; fy: number }> = {
  full: { zoom: 1, fx: 0.5, fy: 0.5 },
  upper: { zoom: 2.1, fx: 0.5, fy: 0.29 },
  face: { zoom: 4.2, fx: 0.5, fy: 0.205 },
};

async function boot() {
  const canvas = document.getElementById('stage') as HTMLCanvasElement;
  const app = new PIXI.Application({ view: canvas, resizeTo: window, backgroundAlpha: 0, antialias: true });
  // More frames wouldn't look any better, and the GPU is shared with TTS and whatever is on screen.
  app.ticker.maxFPS = 60;

  let animator: Animator | null = null;
  let mirror: MirrorArm | null = null;
  // Debug overrides win over the animator; handy for inspecting single parameters.
  const overrides: Record<string, number> = {};
  const rig = await loadRig(
    MODEL_URL,
    (dt) => {
      animator?.update(dt);
      for (const [id, v] of Object.entries(overrides)) rig.params.set(id, v);
    },
    () => {
      animator?.afterPhysics();
      for (const [id, v] of Object.entries(overrides)) rig.params.set(id, v);
      if (animator) mirror?.capture(animator.mirrorActive, animator.mirrorArm);
    },
  );
  const { model } = rig;
  animator = await Animator.create(rig.params);
  app.stage.addChild(model);
  // While a gesture uses the mirrored open hand, hide her own (pointing) right posed arm.
  filterDrawables(model, drawablesUnderPart(model, POINTING_ARM), () => animator!.mirrorActive);

  const view = { ...VIEWS.upper };
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.has('view')) Object.assign(view, VIEWS[hash.get('view') as ViewName] ?? {});
  for (const key of ['zoom', 'fx', 'fy'] as const) if (hash.has(key)) view[key] = Number(hash.get(key));
  const panel = document.getElementById('panel')!;
  const fit = () => {
    const w = model.internalModel.width;
    const h = model.internalModel.height;
    // On wide screens keep her centered in the space left of the side panel.
    const side = window.innerWidth > 640 && !panel.classList.contains('collapsed') ? panel.offsetWidth + 12 : 0;
    const cx = (window.innerWidth - side) / 2;
    const scale = Math.min(window.innerWidth / w, window.innerHeight / h) * view.zoom;
    model.scale.set(scale);
    model.position.set(cx - w * view.fx * scale, window.innerHeight / 2 - h * view.fy * scale);
    mirror?.syncTransform();
  };
  window.addEventListener('resize', fit);
  new ResizeObserver(fit).observe(panel);
  const setView = (name: ViewName) => {
    Object.assign(view, VIEWS[name]);
    fit();
  };

  // Gaze target: pointer position relative to her face, in roughly half-screen units.
  const internal = model.internalModel as any;
  const noseIndex = internal.coreModel.getModel().drawables.ids.indexOf('ArtMesh44');
  const faceScreen = () => {
    const v: Float32Array = internal.getDrawableVertices(noseIndex);
    return model.toGlobal(new PIXI.Point(v[0], v[1]));
  };
  const desktopGaze = new DesktopGaze(animator.gaze, faceScreen);
  app.ticker.add(() => desktopGaze.update());
  // Only needed when the bridge can't say where the mouse is.
  window.addEventListener('pointermove', (e) => {
    if (desktopGaze.live) return;
    const face = faceScreen();
    const reach = Math.max(window.innerWidth, window.innerHeight) * 0.45;
    animator!.gaze.setPointer((e.clientX - face.x) / reach, (face.y - e.clientY) / reach);
  });
  document.documentElement.addEventListener('pointerleave', () => animator!.gaze.pointerLeft());
  window.addEventListener('blur', () => animator!.gaze.pointerLeft());

  // Clicking her head is a head pat; clicking elsewhere on her is a poke.
  canvas.addEventListener('pointerdown', (e) => {
    const face = faceScreen();
    const headRadius = 0.09 * model.internalModel.height * model.scale.y;
    const dx = e.clientX - face.x;
    const dy = e.clientY - face.y;
    if (Math.hypot(dx, dy) < headRadius * 1.4) animator!.react(dy < -headRadius * 0.3 ? 'happy' : 'surprised', 2.5);
    else if (model.getBounds().contains(e.clientX, e.clientY)) animator!.react('embarrassed', 3);
  });

  const speech = new SpeechPlayer(animator);
  const director = new Director(speech);
  director.onShare = (source) => desktopGaze.share(source);
  buildPanel(panel, animator, speech, director, desktopGaze, setView);
  fit();

  // Load the mirrored open-hand arm in the background; gestures wait for nothing.
  void MirrorArm.create(MODEL_URL, rig).then((m) => {
    mirror = m;
    app.stage.addChild(m.model);
    fit();
  });

  // Debug helpers for visual checks from devtools.
  const shots = async (states: Record<string, number>[], settle = 1200) => {
    const out: string[] = [];
    for (const s of states) {
      for (const k of Object.keys(overrides)) delete overrides[k];
      Object.assign(overrides, s);
      await new Promise((r) => setTimeout(r, settle));
      out.push(await app.renderer.extract.base64(app.stage, 'image/jpeg', 0.85, new PIXI.Rectangle(0, 0, window.innerWidth, window.innerHeight)));
    }
    for (const k of Object.keys(overrides)) delete overrides[k];
    return out;
  };
  const capture = () => app.renderer.extract.base64(app.stage, 'image/jpeg', 0.85, new PIXI.Rectangle(0, 0, window.innerWidth, window.innerHeight));
  Object.assign(window as any, { PIXI, app, rig, animator, speech, director, overrides, view, fit, setView, __shots: shots, __capture: capture });
}

boot();
