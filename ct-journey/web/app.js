let lastSpoken = -1;
let camerasActive = false;
let manualMode = false;
let chosenVoice = null;

// Prefer a natural/neural voice (Edge/Chrome ship these as "... Online (Natural)" or
// "Google ... Natural") over the default robotic SAPI voice, for a friendlier companion.
function pickVoice() {
  const voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
  if (!voices.length) return null;
  const english = voices.filter((v) => v.lang && v.lang.toLowerCase().startsWith("en"));
  const pool = english.length ? english : voices;
  const score = (v) => {
    const name = v.name.toLowerCase();
    if (name.includes("natural")) return 3;
    if (name.includes("online") || name.includes("neural")) return 2;
    if (/aria|jenny|libby|sonia|samantha|zira|female/.test(name)) return 1;
    return 0;
  };
  return pool.slice().sort((a, b) => score(b) - score(a))[0];
}

function speak(text) {
  if (!text || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  if (!chosenVoice) chosenVoice = pickVoice();
  if (chosenVoice) utter.voice = chosenVoice;
  utter.rate = 0.97;
  utter.pitch = 1.05;
  window.speechSynthesis.speak(utter);
}

if (window.speechSynthesis) {
  window.speechSynthesis.onvoiceschanged = () => {
    chosenVoice = pickVoice();
  };
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

    document.getElementById("stage-title").textContent = s.title || "";
    document.getElementById("message").textContent = s.message || "";

    manualMode = !!s.manual;
    document.getElementById("next-btn").style.display = manualMode ? "inline-block" : "none";
    document.querySelector(".progress-track").style.display = manualMode ? "none" : "block";
    if (!manualMode) {
      const pct = s.duration > 0 ? Math.min(100, (100 * s.elapsed) / s.duration) : 0;
      document.getElementById("progress").style.width = pct + "%";
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
      speak(s.message);
    }
  } catch (err) {
    console.error(err);
  }
  setTimeout(poll, 600);
}

document.addEventListener(
  "click",
  () => {
    if (window.speechSynthesis && window.speechSynthesis.getVoices().length === 0) {
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(""));
    }
    chosenVoice = pickVoice();
  },
  { once: true }
);

document.getElementById("next-btn").addEventListener("click", () => {
  fetch("/api/next", { method: "POST" }).catch((err) => console.error(err));
});

poll();
