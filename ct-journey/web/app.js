let lastSpoken = -1;
let camerasActive = false;
let manualMode = false;
let currentAudio = null;

// ---------------------------------------------------------------- eye animation
// The eyes shrink/expand in length while Olaf speaks. Real audio-amplitude analysis (via
// Web Audio) drives this when available, so the motion genuinely reflects how loud each
// instant of the sentence is - naturally irregular, not a fixed loop. A randomized-jitter
// fallback (also irregular, just not tied to real audio) covers the browser-TTS path and any
// case where Web Audio can't be set up, WITHOUT ever risking the actual audio output: the
// reactive path only ever engages after confirming the shared AudioContext is running, and
// never partially routes an <audio> element into the Web Audio graph otherwise.
let sharedAudioCtx = null;
let eyeAnimRaf = null;
let eyeAnimTimer = null;

function ensureAudioContext() {
  if (!sharedAudioCtx) {
    try {
      sharedAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    } catch (err) {
      sharedAudioCtx = null;
    }
  }
  if (sharedAudioCtx && sharedAudioCtx.state === "suspended") {
    sharedAudioCtx.resume().catch(() => {});
  }
  return sharedAudioCtx;
}

// Used by the speaking-time animations (reactive/jitter) - always resets to a short, fixed
// transition first so a lingering long blink transition can never bleed into this and make
// the speaking pulse feel laggy.
function setEyeScale(scale) {
  document.querySelectorAll(".eye").forEach((e) => {
    e.style.transition = "transform 0.12s ease-in-out";
    e.style.transform = scale == null ? "" : `scaleY(${scale})`;
  });
}

function stopEyeAnim() {
  if (eyeAnimRaf) {
    cancelAnimationFrame(eyeAnimRaf);
    eyeAnimRaf = null;
  }
  if (eyeAnimTimer) {
    clearTimeout(eyeAnimTimer);
    eyeAnimTimer = null;
  }
  setEyeScale(null);
}

// Random, irregular pulsing - not a smooth fixed loop. Both the size and the timing between
// pulses are randomized each cycle so it never settles into an obviously repeating pattern.
function startRandomEyeJitter() {
  const pulse = () => {
    const scale = 0.55 + Math.random() * 0.45;
    setEyeScale(scale);
    eyeAnimTimer = setTimeout(pulse, 110 + Math.random() * 240);
  };
  pulse();
}

// True audio-reactive pulsing: analyses the actual TTS audio as it plays and maps its
// real-time loudness onto the eyes. Only engages if the shared AudioContext is confirmed
// running - otherwise returns false and the caller falls back to startRandomEyeJitter()
// instead, so audio playback itself is never put at risk.
function tryAttachReactiveEyes(audioEl) {
  const ctx = ensureAudioContext();
  if (!ctx || ctx.state !== "running") return false;
  try {
    const source = ctx.createMediaElementSource(audioEl);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.55;
    source.connect(analyser);
    analyser.connect(ctx.destination);  // must still reach the speakers
    const data = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sumSq = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sumSq += v * v;
      }
      const rms = Math.sqrt(sumSq / data.length);
      const scale = Math.max(0.4, 1 - rms * 2.6);
      setEyeScale(scale);
      eyeAnimRaf = requestAnimationFrame(tick);
    };
    tick();
    return true;
  } catch (err) {
    console.error("reactive eyes attach failed, falling back to jitter:", err);
    return false;
  }
}

// Idle blink cycle, copied frame-for-frame off a reference animation (measured at ~15fps):
// that clip loops every exactly 25s with these 10 blink events (offset/close/hold/open in ms
// from the start of the cycle, min = how much the eye's height shrinks to at the bottom of
// the blink, 1 = fully open). Mixes quick full blinks, slow partial squints and one near-
// instant flutter, at irregular intervals - copied as-is rather than approximated.
const BLINK_EVENTS = [
  { offset: 1270, close: 150, hold: 80, open: 150, min: 0.07 },
  { offset: 5470, close: 160, hold: 100, open: 160, min: 0.13 },
  { offset: 6930, close: 230, hold: 210, open: 230, min: 0.74 },
  { offset: 9070, close: 350, hold: 300, open: 350, min: 0.76 },
  { offset: 13270, close: 330, hold: 270, open: 330, min: 0.44 },
  { offset: 15200, close: 200, hold: 400, open: 200, min: 0.14 },
  { offset: 17200, close: 120, hold: 90, open: 120, min: 0.25 },
  { offset: 20400, close: 100, hold: 70, open: 100, min: 0.89 },
  { offset: 21530, close: 25, hold: 20, open: 25, min: 0.88 },
  { offset: 22400, close: 330, hold: 800, open: 200, min: 0.35 },
];
const BLINK_CYCLE_MS = 25000;

function runBlinkEvent({ close, hold, open, min }) {
  const faceEl = document.getElementById("face");
  if (!faceEl || faceEl.classList.contains("face-hidden") || faceEl.classList.contains("speaking")) return;
  document.querySelectorAll(".eye").forEach((e) => {
    e.style.transition = `transform ${close}ms ease-in-out`;
    e.style.transform = `scaleY(${min})`;
  });
  setTimeout(() => {
    document.querySelectorAll(".eye").forEach((e) => {
      e.style.transition = `transform ${open}ms ease-in-out`;
      e.style.transform = "";
    });
  }, close + hold);
}

function scheduleBlinkCycle() {
  BLINK_EVENTS.forEach((ev) => setTimeout(() => runBlinkEvent(ev), ev.offset));
}
scheduleBlinkCycle();
setInterval(scheduleBlinkCycle, BLINK_CYCLE_MS);

// A browser mirroring the robot's screen (e.g. the laptop watching the demo) adds
// ?mute=1 to skip speech synthesis and ?readonly=1 to hide the manual "Next"/"Listen"
// buttons - otherwise every mirrored tab would also talk and could control the robot.
const viewParams = new URLSearchParams(window.location.search);
const isMuted = viewParams.get("mute") === "1";
const isReadonly = viewParams.get("readonly") === "1";

// ---------------------------------------------------------------- speech (ElevenLabs first)
// Olaf's real voice: synthesized server-side by ElevenLabs (see tts.py), so it sounds the
// same everywhere regardless of what TTS engine (often robotic) happens to be installed on
// the viewing device. Falls back to the browser's built-in voice only if that request fails,
// so the robot is never silently mute.
let chosenVoice = null;
const FEMALE_VOICE_NAMES = /female|woman|\bzira\b|\bhazel\b|\baria\b|\bjenny\b|\blibby\b|\bsonia\b|\bsamantha\b|\bsusan\b|\blinda\b|\bheera\b|\braveena\b|\bjoanna\b|\bkendra\b|\bkimberly\b|\bsalli\b|\bivy\b|\beva\b|\bkaren\b|\bmoira\b|\btessa\b|\bveena\b|\bfiona\b|\bvictoria\b|\bemma\b|\bamelia\b|\bolivia\b|\bgoogle us english\b/i;
const MALE_VOICE_NAMES = /\bmale\b|\bman\b|\bdavid\b|\bmark\b|\bguy\b|\bdaniel\b|\bmatthew\b|\bjustin\b|\bbrian\b|\beric\b|\bgeorge\b|\bkevin\b|\bryan\b/i;

function pickBrowserVoice() {
  const voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
  if (!voices.length) return null;
  const english = voices.filter((v) => v.lang && v.lang.toLowerCase().startsWith("en"));
  const pool = english.length ? english : voices;
  const score = (v) => {
    const name = v.name.toLowerCase();
    let s = 0;
    if (FEMALE_VOICE_NAMES.test(name)) s += 10;
    else if (MALE_VOICE_NAMES.test(name)) s -= 10;
    if (name.includes("natural")) s += 3;
    if (name.includes("online") || name.includes("neural")) s += 2;
    return s;
  };
  return pool.slice().sort((a, b) => score(b) - score(a))[0];
}

if (window.speechSynthesis) {
  window.speechSynthesis.onvoiceschanged = () => {
    chosenVoice = pickBrowserVoice();
  };
}

function speakBrowserFallback(text, faceEl) {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  if (!chosenVoice) chosenVoice = pickBrowserVoice();
  if (chosenVoice) utter.voice = chosenVoice;
  utter.rate = 0.97;
  utter.pitch = 1.05;
  // No access to this audio's real waveform, so just the randomized jitter here.
  utter.onstart = () => {
    faceEl.classList.add("speaking");
    startRandomEyeJitter();
  };
  utter.onend = utter.onerror = () => {
    faceEl.classList.remove("speaking");
    stopEyeAnim();
  };
  window.speechSynthesis.speak(utter);
}

async function speak(text) {
  const faceEl = document.getElementById("face");
  if (!text || !faceEl) return;
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  stopEyeAnim();
  try {
    const res = await fetch(`/api/tts?text=${encodeURIComponent(text)}`);
    if (!res.ok) throw new Error("tts http " + res.status);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudio = audio;
    audio.onplay = () => {
      faceEl.classList.add("speaking");
      if (!tryAttachReactiveEyes(audio)) startRandomEyeJitter();
    };
    audio.onended = audio.onerror = () => {
      faceEl.classList.remove("speaking");
      stopEyeAnim();
      URL.revokeObjectURL(url);
    };
    await audio.play();
  } catch (err) {
    console.error("local TTS failed, falling back to browser voice:", err);
    speakBrowserFallback(text, faceEl);
  }
}

function setBadge(el, text, cls) {
  if (!text) {
    el.style.display = "none";
    return;
  }
  el.textContent = text;
  el.className = "badge " + cls;
  el.style.display = "inline-block";
}

async function poll() {
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    const s = await res.json();

    // Nothing (camera included) starts until a source is chosen on this pre-connect screen -
    // see runner.py JourneyRunner._source_chosen. Once state reports one, switch over to the
    // normal journey UI and never show this screen again for the rest of the run.
    const sourceSelect = document.getElementById("source-select");
    const layout = document.getElementById("layout");
    if (sourceSelect && layout) {
      const chosen = !!s.camera_source;
      sourceSelect.style.display = chosen ? "none" : "flex";
      layout.style.display = chosen ? "flex" : "none";
    }

    document.getElementById("stage-title").textContent = s.title || "";
    document.getElementById("message").textContent = s.message || "";

    manualMode = !!s.manual;
    document.getElementById("next-btn").style.display = manualMode && !isReadonly ? "inline-block" : "none";
    document.querySelector(".progress-track").style.display = manualMode ? "none" : "block";
    if (!manualMode) {
      const pct = s.duration > 0 ? Math.min(100, (100 * s.elapsed) / s.duration) : 0;
      document.getElementById("progress").style.width = pct + "%";
    }

    // Olaf's face is the whole screen while idle/talking/listening - only real camera
    // sensing (s.watching) switches over to the live feed + status text instead. Everything
    // else (message text, badges, examples) is hidden while the face is up, by design: just
    // the eyes and mouth.
    const faceEl = document.getElementById("face");
    const showFace = !!s.listening || !s.watching;
    faceEl.classList.toggle("face-hidden", !showFace);
    faceEl.classList.toggle("listening", !!s.listening);

    document.body.classList.toggle("face-mode", showFace);

    const heardEl = document.getElementById("heard-text");
    if (heardEl) {
      if (s.heard_text && !s.listening) {
        heardEl.textContent = `"${s.heard_text}"`;
        heardEl.style.display = "block";
      } else {
        heardEl.style.display = "none";
      }
    }

    // The camera panel only shows while the robot is actually using the camera this
    // stage (looking for/tracking/checking the patient) - hidden the rest of the time.
    const panel = document.getElementById("camera-panel");
    const liveCam = document.getElementById("live-cam");
    panel.style.display = s.watching ? "flex" : "none";
    if (s.watching && !camerasActive) {
      camerasActive = true;
      liveCam.src = `/api/camera/stream.mjpg?t=${Date.now()}`;
    } else if (!s.watching && camerasActive) {
      camerasActive = false;
      liveCam.src = "";  // closes the stream connection until it's needed again
    }

    // The alignment guide only makes sense during face-identify stages; it turns solid
    // green once the backend agrees the face is centered/close enough to actually match.
    const frameEl = document.getElementById("face-frame");
    const captionEl = document.getElementById("cam-caption");
    if (frameEl && captionEl) {
      const isIdentifyStage = ["waiting_room_call", "confirm_at_changing_room", "confirm_after_changing"].includes(s.stage_id);
      if (isIdentifyStage && s.watching) {
        frameEl.style.display = "block";
        frameEl.classList.toggle("aligned", s.face_aligned === true);
        captionEl.textContent =
          s.face_aligned === true ? "Got it!" :
          s.face_aligned === false ? "Step into the frame and face the camera" :
          "Looking for you...";
      } else {
        frameEl.style.display = "none";
        captionEl.textContent = "Looking for you...";
      }
    }

    const trackEl = document.getElementById("track-badge");
    const patients = s.track_status && s.track_status.patients;
    if (patients && patients.length) {
      const p = patients[0];
      setBadge(trackEl, `Tracking ${p.name || p.patient_id}: ${p.state}`, p.state === "present" ? "ok" : "warn");
    } else {
      setBadge(trackEl, null, "");
    }

    const postureEl = document.getElementById("posture-badge");
    if (s.posture_status) {
      const cls = s.posture_status === "WITHIN_CRITERIA" ? "ok" : s.posture_status === "UNCERTAIN" ? "warn" : "bad";
      setBadge(postureEl, `Posture: ${s.posture_status}`, cls);
    } else {
      setBadge(postureEl, null, "");
    }

    const examplesEl = document.getElementById("examples");
    examplesEl.innerHTML = "";
    (s.example_images || []).forEach((name) => {
      const img = document.createElement("img");
      img.src = `/api/examples/${name}`;
      examplesEl.appendChild(img);
    });

    if (s.speak_seq !== lastSpoken) {
      lastSpoken = s.speak_seq;
      if (!isMuted) speak(s.message);
    }
  } catch (err) {
    console.error(err);
  }
  setTimeout(poll, 600);
}

// Guarded against missing elements: a WebView that cached an older index.html alongside a
// freshly-fetched app.js (version skew) must not throw here and abort the whole script -
// that would silently kill poll() below and leave the page stuck on its static placeholder.
const nextBtn = document.getElementById("next-btn");
if (nextBtn) {
  nextBtn.addEventListener("click", () => {
    fetch("/api/next", { method: "POST" }).catch((err) => console.error(err));
  });
}

// Pre-connect camera-source buttons. Disabled on a mirroring/readonly view - this is a
// once-per-run operator decision, not something a second browser tab should be able to make.
async function chooseSource(source) {
  const statusEl = document.getElementById("source-status");
  const buttons = document.querySelectorAll(".source-btn");
  buttons.forEach((b) => (b.disabled = true));
  document.getElementById(`source-${source}`).classList.add("chosen");
  if (statusEl) statusEl.textContent = "Connecting...";
  try {
    const res = await fetch("/api/camera-source", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    if (!res.ok) throw new Error("http " + res.status);
  } catch (err) {
    console.error("camera-source choice failed:", err);
    if (statusEl) statusEl.textContent = "Couldn't reach the server - try again.";
    buttons.forEach((b) => (b.disabled = false));
    document.getElementById(`source-${source}`).classList.remove("chosen");
  }
}

const sourceExternalBtn = document.getElementById("source-external");
const sourceRobotBtn = document.getElementById("source-robot");
if (sourceExternalBtn && sourceRobotBtn) {
  if (isReadonly) {
    sourceExternalBtn.disabled = true;
    sourceRobotBtn.disabled = true;
    const statusEl = document.getElementById("source-status");
    if (statusEl) statusEl.textContent = "Waiting for the camera source to be chosen on the robot...";
  } else {
    sourceExternalBtn.addEventListener("click", () => chooseSource("external"));
    sourceRobotBtn.addEventListener("click", () => chooseSource("robot"));
  }
}

const listenBtn = document.getElementById("listen-btn");
if (listenBtn) {
  if (!isReadonly) listenBtn.style.display = "inline-block";
  listenBtn.addEventListener("click", async () => {
    listenBtn.disabled = true;
    listenBtn.textContent = "\u{1F3A4} Listening...";
    try {
      await fetch("/api/listen", { method: "POST" });
    } catch (err) {
      console.error(err);
    }
    listenBtn.disabled = false;
    listenBtn.textContent = "\u{1F3A4} Listen";
  });
}

// Browsers only allow starting/resuming an AudioContext after a real user gesture - warm it
// up on the first tap anywhere (almost always the camera-source choice), so by the time
// Olaf's first line plays, reactive eyes can actually engage.
document.addEventListener("click", () => ensureAudioContext(), { once: true });

poll();
