// The 3D sky behind the page: haze particles show the air, the sun shows the heat.
// After a report loads: worse AQI -> denser, darker, more coloured haze; hotter -> bigger, redder sun.
// Degrades to a CSS gradient when WebGL/Three.js is unavailable or the user prefers reduced motion.
(function () {
  const root = document.documentElement;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const api = { set() {} };
  window.SaansScene = api;

  const SKY = [ // [aqi limit, haze colour, sky tint, haze colour on a light sky]
    [50, 0x7dd3fc, "#0b3b5c", 0x0284c7], [100, 0xa3e635, "#0f3d3a", 0x4d7c0f], [200, 0xfacc15, "#3d3a12", 0xa16207],
    [300, 0xfb923c, "#4a2a12", 0xc2410c], [400, 0xef4444, "#4a1515", 0xb91c1c], [1e9, 0xa21caf, "#3a0f2e", 0x86198f],
  ];
  const skyFor = (aqi) => SKY.find(([lim]) => aqi <= lim);

  function setCssSky(aqi) {
    root.style.setProperty("--sky", aqi == null ? "" : skyFor(aqi)[2]);
  }

  const canvas = document.getElementById("sky");
  if (!canvas || !window.THREE || reduced) {
    api.set = ({ aqi }) => setCssSky(aqi);
    return;
  }
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: "low-power" });
  } catch {
    api.set = ({ aqi }) => setCssSky(aqi);
    return;
  }

  const mobile = Math.min(innerWidth, innerHeight) < 700;
  // Additive glow vanishes on a pale sky, so light mode uses normal blending and deeper colours.
  const light = matchMedia("(prefers-color-scheme: light)").matches && root.dataset.theme !== "dark";
  const blend = light ? THREE.NormalBlending : THREE.AdditiveBlending;
  const N = mobile ? 1400 : 3200;
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 200);
  camera.position.set(0, 0, 30);

  // --- soft round particle sprite
  const dot = document.createElement("canvas");
  dot.width = dot.height = 64;
  const g = dot.getContext("2d");
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.35, "rgba(255,255,255,.55)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  const sprite = new THREE.CanvasTexture(dot);

  // --- haze: particles drifting on the wind through a deep box
  const pos = new Float32Array(N * 3), speed = new Float32Array(N), phase = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    pos[i * 3] = (Math.random() - 0.5) * 90;
    pos[i * 3 + 1] = (Math.random() - 0.5) * 50;
    pos[i * 3 + 2] = (Math.random() - 0.5) * 60 - 5;
    speed[i] = 0.6 + Math.random() * 1.4;
    phase[i] = Math.random() * Math.PI * 2;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const haze = new THREE.PointsMaterial({
    map: sprite, size: 0.9, transparent: true, depthWrite: false, opacity: 0.55,
    color: light ? 0x0284c7 : 0x7dd3fc, blending: blend, sizeAttenuation: true,
  });
  const points = new THREE.Points(geo, haze);
  scene.add(points);

  // --- sun: core + additive glow halo
  const sun = new THREE.Group();
  // camera-facing disc: a sphere this far off-axis gets stretched by perspective
  const disc = document.createElement("canvas");
  disc.width = disc.height = 128;
  const dg = disc.getContext("2d"), dgrad = dg.createRadialGradient(64, 64, 0, 64, 64, 64);
  dgrad.addColorStop(0, "#fff"); dgrad.addColorStop(0.82, "#fff"); dgrad.addColorStop(1, "rgba(255,255,255,0)");
  dg.fillStyle = dgrad; dg.fillRect(0, 0, 128, 128);
  const core = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(disc), color: 0xffd27a, transparent: true, depthWrite: false }));
  core.scale.set(4.6, 4.6, 1);
  const glowMat = new THREE.SpriteMaterial({ map: sprite, color: 0xffb347, transparent: true, opacity: light ? 0.45 : 0.7, blending: blend, depthWrite: false });
  const glow = new THREE.Sprite(glowMat);
  glow.scale.set(16, 16, 1);
  sun.add(glow, core);
  sun.position.set(mobile ? 8 : 30, mobile ? 17 : 18, -14);
  scene.add(sun);

  // --- targets that the report drives; current values ease toward them
  const target = { color: new THREE.Color(light ? 0x0284c7 : 0x7dd3fc), density: 0.45, opacity: light ? 0.3 : 0.5, sunScale: 1, sunColor: new THREE.Color(0xffd27a), wind: 1 };
  const cur = { density: 0.45, sunScale: 1 };

  api.set = ({ aqi, feels }) => {
    setCssSky(aqi);
    if (aqi != null) {
      target.color.setHex(skyFor(aqi)[light ? 3 : 1]);
      const k = Math.min(aqi, 450) / 450; // 0 clean .. 1 severe
      target.density = 0.25 + 0.75 * k;
      target.opacity = light ? 0.22 + 0.33 * k : 0.35 + 0.45 * k;
      target.wind = 1.4 - 1.0 * k; // stagnant air on bad days
    }
    if (feels != null) {
      const h = Math.max(0, Math.min(1, (feels - 24) / 26)); // 24C -> 0, 50C -> 1
      target.sunScale = 0.7 + 1.1 * h;
      target.sunColor.setHSL(0.13 - 0.12 * h, 1, 0.62 - 0.1 * h);
    }
  };

  let mx = 0, my = 0;
  addEventListener("pointermove", (e) => { mx = e.clientX / innerWidth - 0.5; my = e.clientY / innerHeight - 0.5; }, { passive: true });

  function resize() {
    const w = innerWidth, h = innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  addEventListener("resize", resize);
  resize();

  const clock = new THREE.Clock();
  let running = true;
  document.addEventListener("visibilitychange", () => { running = !document.hidden; if (running) { clock.getDelta(); loop(); } });

  function loop() {
    if (!running) return;
    const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
    const ease = 1 - Math.pow(0.04, dt);

    haze.color.lerp(target.color, ease);
    haze.opacity += (target.opacity - haze.opacity) * ease;
    cur.density += (target.density - cur.density) * ease;
    geo.setDrawRange(0, Math.floor(N * cur.density));

    const a = geo.attributes.position.array;
    for (let i = 0; i < N; i++) {
      a[i * 3] += speed[i] * target.wind * dt;
      a[i * 3 + 1] += Math.sin(t * 0.5 + phase[i]) * 0.004;
      if (a[i * 3] > 45) a[i * 3] = -45;
    }
    geo.attributes.position.needsUpdate = true;

    cur.sunScale += (target.sunScale - cur.sunScale) * ease;
    const pulse = 1 + Math.sin(t * 1.6) * 0.03;
    sun.scale.setScalar(cur.sunScale * pulse);
    core.material.color.lerp(target.sunColor, ease);
    glowMat.color.lerp(target.sunColor, ease);

    // scroll moves the camera down through the haze; pointer adds gentle parallax
    const scroll = Math.min(scrollY / innerHeight, 2);
    camera.position.x += (mx * 4 - camera.position.x) * 0.04;
    camera.position.y += (-my * 3 - scroll * 4 - camera.position.y) * 0.04;
    camera.lookAt(0, -scroll * 4, -10);
    points.rotation.y = Math.sin(t * 0.05) * 0.12;

    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  }
  loop();
})();
