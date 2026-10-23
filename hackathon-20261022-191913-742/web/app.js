"use strict";

const $ = (id) => document.getElementById(id);
const state = {settings: null, image: null, base64: null, result: null, overlay: null, view: "input", editing: false, dragging: null, rect: null, table: null, version: 0, busy: false};
const labels = {WITHIN_CRITERIA: "Within criteria", REPOSITION_REQUIRED: "Reposition required", UNCERTAIN: "Uncertain", ALONGSIDE_BODY: "Alongside body", ARMS_RAISED: "Arms raised", OVER_TORSO: "Over torso", MIXED: "Mixed posture"};
const reasonLabels = {configured_2d_checks_passed: "Configured 2D checks passed.", lateral_offset: "Torso is outside the lateral tolerance.", axis_error: "Body axis exceeds the alignment tolerance.", longitudinal_offset: "Torso is outside the longitudinal tolerance.", arm_posture_not_allowed: "Arm posture does not match the selected policy.", low_or_invalid_arm_confidence: "Arm landmarks are missing or low-confidence.", arm_geometry_unclassified: "Arm geometry cannot be classified reliably.", insufficient_projected_shoulder_width: "Shoulder projection is too narrow for an arm assessment.", no_patient_on_table: "No reliable patient detected on the bed.", ambiguous_multiple_people: "More than one patient candidate overlaps the bed.", low_or_invalid_landmark_confidence: "Torso landmarks are missing or low-confidence.", torso_landmarks_outside_table: "Required torso landmarks are outside the bed.", table_setup_not_confirmed: "Bed reference has not been confirmed.", uncalibrated_perspective_or_unconfirmed_nadir: "A near-overhead view or measured calibration is required.", degenerate_torso_geometry: "Torso geometry is not reliable.", implausible_projected_arm_geometry: "Projected arm geometry is not reliable."};

function icons() { if (window.lucide) window.lucide.createIcons(); }
function setError(message = "") { $("error").textContent = message; $("error").hidden = !message; }
function resetResult() {
  state.version += 1;
  state.result = null; state.overlay = null; state.view = "input";
  $("decision").className = "decision neutral";
  $("status").textContent = "Not assessed"; $("status-code").textContent = state.image ? "READY_FOR_ASSESSMENT" : "AWAITING_IMAGE";
  $("status-icon").innerHTML = '<i data-lucide="circle-dashed"></i>';
  $("reasons").replaceChildren(Object.assign(document.createElement("li"), {textContent: "No assessment yet."}));
  for (const id of ["lateral", "angle", "longitudinal", "lateral-limit", "angle-limit", "confidence", "inference", "processing", "left-arm", "right-arm", "arm-policy"]) $(id).textContent = "\u2014";
  $("longitudinal-limit").textContent = "Not configured";
  $("arm-posture").textContent = "Not observed";
  $("event").textContent = "No assessment yet.";
  $("download-image").disabled = true; $("download-json").disabled = true; $("overlay-tab").disabled = true;
  setBusy(false); selectView("input"); icons();
}
function setBusy(value) { state.busy = value; $("busy").hidden = !value; $("analyze").disabled = value || !state.image; }
function selectedProfile() { return state.settings.profiles.find((profile) => profile.id === $("profile").value); }
function rectFromCorners(corners) { return {left: Math.min(...corners.map((point) => point[0])), right: Math.max(...corners.map((point) => point[0])), top: Math.min(...corners.map((point) => point[1])), bottom: Math.max(...corners.map((point) => point[1]))}; }
function setOrientation(corners) {
  const headX = (corners[0][0] + corners[1][0]) / 2, headY = (corners[0][1] + corners[1][1]) / 2;
  const tailX = (corners[2][0] + corners[3][0]) / 2, tailY = (corners[2][1] + corners[3][1]) / 2;
  $("orientation").value = Math.abs(tailX - headX) > Math.abs(tailY - headY) ? (headX < tailX ? "LEFT" : "RIGHT") : (headY < tailY ? "TOP" : "BOTTOM");
}
function updateTable() {
  const {left, right, top, bottom} = state.rect;
  const options = {LEFT: [[left,bottom],[left,top],[right,top],[right,bottom]], RIGHT: [[right,top],[right,bottom],[left,bottom],[left,top]], TOP: [[left,top],[right,top],[right,bottom],[left,bottom]], BOTTOM: [[right,bottom],[left,bottom],[left,top],[right,top]]};
  state.table = {corners_normalized: options[$("orientation").value], confirmed: $("confirmed").checked, near_nadir: $("nadir").checked};
  $("reference-label").textContent = state.table.confirmed ? "Bed reference confirmed" : "Bed reference unconfirmed";
}
function applyProfile() {
  const profile = selectedProfile();
  state.rect = rectFromCorners(profile.table.corners_normalized);
  state.table = structuredClone(profile.table);
  $("confirmed").checked = profile.table.confirmed; $("nadir").checked = profile.table.near_nadir;
  setOrientation(profile.table.corners_normalized); updateTable(); resetResult(); draw();
}
function fitRect(width, height, targetWidth, targetHeight) { const scale = Math.min(targetWidth / width, targetHeight / height); return {x: (targetWidth - width * scale) / 2, y: (targetHeight - height * scale) / 2, width: width * scale, height: height * scale}; }
function draw() {
  const canvas = $("canvas"), bounds = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(bounds.width * devicePixelRatio)); canvas.height = Math.max(1, Math.round(bounds.height * devicePixelRatio));
  const context = canvas.getContext("2d"); context.clearRect(0, 0, canvas.width, canvas.height);
  if (!state.image) return;
  if (state.view === "overlay" && state.overlay && !state.editing) {
    const fit = fitRect(state.overlay.width, state.overlay.height, canvas.width, canvas.height);
    context.drawImage(state.overlay, fit.x, fit.y, fit.width, fit.height); return;
  }
  const image = state.image;
  const {left, right, top, bottom} = state.rect;
  if (state.editing) {
    const fit = fitRect(image.width, image.height, canvas.width, canvas.height);
    context.drawImage(image, fit.x, fit.y, fit.width, fit.height);
    context.fillStyle = "rgba(10,22,16,.65)"; context.fillRect(fit.x, fit.y, fit.width, fit.height);
    const x = fit.x + left * fit.width, y = fit.y + top * fit.height, width = (right - left) * fit.width, height = (bottom - top) * fit.height;
    context.drawImage(image, left * image.width, top * image.height, (right-left)*image.width, (bottom-top)*image.height, x, y, width, height);
    context.strokeStyle = "#57e1bb"; context.lineWidth = 2 * devicePixelRatio; context.strokeRect(x, y, width, height);
    context.fillStyle = "#57e1bb";
    for (const [cornerX,cornerY] of [[x,y],[x+width,y],[x+width,y+height],[x,y+height]]) context.fillRect(cornerX-3*devicePixelRatio, cornerY-3*devicePixelRatio, 6*devicePixelRatio, 6*devicePixelRatio);
  } else {
    const width = (right-left)*image.width, height = (bottom-top)*image.height;
    const fit = fitRect(width, height, canvas.width, canvas.height);
    context.drawImage(image, left*image.width, top*image.height, width, height, fit.x, fit.y, fit.width, fit.height);
  }
}
function selectView(view) { state.view = view; $("input-tab").setAttribute("aria-selected", String(view === "input")); $("overlay-tab").setAttribute("aria-selected", String(view === "overlay")); draw(); }
function editBed(value) { state.editing = value; $("bed-editor").hidden = !value; $("edit").classList.toggle("active", value); $("canvas").classList.toggle("editing", value); $("view-label").textContent = value ? "Bed reference editor" : "Bed region only"; draw(); }
async function loadBlob(blob, name) {
  if (!blob || !blob.type.startsWith("image/")) { setError("Select a supported image file."); return; }
  if (blob.size > 12 * 1024 * 1024) { setError("Image exceeds 12 MB. Resize it before uploading."); return; }
  setError(); resetResult(); editBed(false);
  const version = state.version;
  try {
    const dataUrl = await new Promise((resolve,reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob); });
    const image = await new Promise((resolve,reject) => { const candidate = new Image(); candidate.onload = () => resolve(candidate); candidate.onerror = reject; candidate.src = dataUrl; });
    if (version !== state.version) return;
    if (image.width * image.height > 20000000) throw new Error("Image exceeds 20 megapixels. Resize it before uploading.");
    state.image = image; state.base64 = dataUrl.split(",")[1];
    $("filename").textContent = name || "Pasted image"; $("image-info").textContent = `${image.width} \u00d7 ${image.height} px`;
    $("empty").hidden = true; $("clear").disabled = false; $("edit").disabled = false; $("analyze").disabled = false;
    $("status-code").textContent = "READY_FOR_ASSESSMENT"; draw();
  } catch (error) { setError(error.message || "This image could not be opened."); }
}
function percent(value, signed = true) { return `${signed && value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%`; }
function showResult(result) {
  const event = result.event, measurements = event.measurements, arms = event.arm_assessment;
  state.result = result;
  $("status").textContent = labels[event.status] || event.status; $("status-code").textContent = event.status;
  const kind = event.status === "WITHIN_CRITERIA" ? "pass" : event.status === "REPOSITION_REQUIRED" ? "fail" : "unknown";
  $("decision").className = `decision ${kind}`;
  $("status-icon").innerHTML = `<i data-lucide="${kind === "pass" ? "circle-check" : kind === "fail" ? "circle-alert" : "circle-help"}"></i>`;
  $("reasons").replaceChildren(...event.reasons.map((reason) => Object.assign(document.createElement("li"), {textContent: reasonLabels[reason] || reason.replaceAll("_", " ")})));
  $("lateral").textContent = measurements.center_offset_fraction == null ? "\u2014" : percent(measurements.center_offset_fraction);
  $("lateral-limit").textContent = `Limit: \u00b1${percent(result.limits.lateral_fraction,false)} of bed width`;
  $("angle").textContent = measurements.axis_error_deg == null ? "\u2014" : `${measurements.axis_error_deg.toFixed(1)}\u00b0`;
  $("angle-limit").textContent = `Limit: ${result.limits.angle_deg.toFixed(1)}\u00b0`;
  $("longitudinal").textContent = measurements.longitudinal_offset_fraction == null ? "\u2014" : percent(measurements.longitudinal_offset_fraction);
  $("longitudinal-limit").textContent = result.limits.longitudinal_fraction == null ? "Not configured" : `Limit: \u00b1${percent(result.limits.longitudinal_fraction,false)} of bed length`;
  $("arm-posture").textContent = arms ? labels[arms.posture] || arms.posture : "Not observed";
  $("left-arm").textContent = arms ? labels[arms.left] || arms.left : "\u2014"; $("right-arm").textContent = arms ? labels[arms.right] || arms.right : "\u2014";
  $("arm-policy").textContent = arms ? (arms.policy_enabled ? "Required" : "Observation only") : "\u2014";
  $("confidence").textContent = event.perception_confidence == null ? "Unavailable" : event.perception_confidence.toFixed(3);
  $("inference").textContent = `${Math.round(event.inference_ms)} ms`; $("processing").textContent = `${Math.round(event.processing_ms)} ms`; $("model").textContent = result.model;
  $("event").textContent = JSON.stringify(event,null,2); $("download-json").disabled = false;
  const overlay = new Image(); overlay.onload = () => { if (state.result !== result) return; state.overlay = overlay; $("overlay-tab").disabled = false; $("download-image").disabled = false; selectView("overlay"); }; overlay.src = `data:image/jpeg;base64,${result.annotation}`;
  icons();
}
async function analyze() {
  if (!state.image || state.busy) return;
  editBed(false); resetResult(); setError(); setBusy(true);
  const version = state.version;
  const payload = {image: state.base64, profile: $("profile").value, table: state.table};
  const policy = $("policy").value;
  if (policy !== "PROFILE") payload.allowed_postures = policy === "OBSERVE" ? null : [policy];
  try {
    const response = await fetch("/api/analyze", {method: "POST", headers: {"Content-Type":"application/json"}, body:JSON.stringify(payload)});
    const result = await response.json();
    if (version !== state.version) return;
    if (!response.ok) throw new Error(result.error || "Analysis failed.");
    showResult(result);
  } catch (error) { if (version === state.version) setError(error.message || "Unable to connect to the local analysis server."); }
  finally { if (version === state.version) setBusy(false); }
}
function download(blob, filename) { const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000); }
function pointerPosition(event) { const bounds = $("canvas").getBoundingClientRect(); const fit = fitRect(state.image.width,state.image.height,bounds.width,bounds.height); return {x:Math.max(0,Math.min(1,(event.clientX-bounds.left-fit.x)/fit.width)), y:Math.max(0,Math.min(1,(event.clientY-bounds.top-fit.y)/fit.height))}; }
$("canvas").addEventListener("pointerdown", (event) => { if (!state.editing || !state.image) return; state.dragging = pointerPosition(event); $("canvas").setPointerCapture(event.pointerId); event.preventDefault(); });
$("canvas").addEventListener("pointermove", (event) => { if (!state.dragging) return; const position = pointerPosition(event), start = state.dragging; state.rect = {left:Math.min(start.x,position.x),right:Math.max(start.x,position.x),top:Math.min(start.y,position.y),bottom:Math.max(start.y,position.y)}; draw(); });
$("canvas").addEventListener("pointerup", () => { if (!state.dragging) return; state.dragging = null; if (state.rect.right-state.rect.left < .01 || state.rect.bottom-state.rect.top < .01) { state.rect = rectFromCorners(state.table.corners_normalized); draw(); return; } $("confirmed").checked = false; updateTable(); resetResult(); draw(); });
$("canvas").addEventListener("pointercancel", () => { state.dragging = null; if (state.table) state.rect = rectFromCorners(state.table.corners_normalized); draw(); });
$("upload").onclick = $("choose").onclick = () => $("file").click();
$("file").onchange = (event) => { if (event.target.files[0]) loadBlob(event.target.files[0],event.target.files[0].name); event.target.value = ""; };
document.addEventListener("paste", (event) => { const item = [...(event.clipboardData?.items || [])].find((item) => item.type.startsWith("image/")); if (item) { event.preventDefault(); $("sample").value = ""; loadBlob(item.getAsFile(),"Pasted image"); } });
$("paste").onclick = async () => { try { const items = await navigator.clipboard.read(); for (const item of items) { const type = item.types.find((type) => type.startsWith("image/")); if (type) { $("sample").value = ""; await loadBlob(await item.getType(type),"Pasted image"); return; } } setError("No image was found on the clipboard."); } catch { setError("Clipboard access was not granted. Paste the image into this page or use Upload."); } };
for (const eventName of ["dragenter","dragover"]) $("dropzone").addEventListener(eventName, (event) => { event.preventDefault(); $("dropzone").classList.add("dragging"); });
$("dropzone").addEventListener("dragleave", () => $("dropzone").classList.remove("dragging"));
$("dropzone").addEventListener("drop", (event) => { event.preventDefault(); $("dropzone").classList.remove("dragging"); if (event.dataTransfer.files[0]) { $("sample").value = ""; loadBlob(event.dataTransfer.files[0],event.dataTransfer.files[0].name); } });
$("clear").onclick = () => { state.image = null; state.base64 = null; resetResult(); editBed(false); $("filename").textContent = "No image selected"; $("image-info").textContent = "\u2014"; $("empty").hidden = false; $("file").value = ""; $("sample").value = ""; $("edit").disabled = true; $("clear").disabled = true; setError(); draw(); };
$("analyze").onclick = analyze; $("profile").onchange = () => { setError(); editBed(false); applyProfile(); };
$("policy").onchange = () => { resetResult(); setError(); };
$("input-tab").onclick = () => selectView("input"); $("overlay-tab").onclick = () => selectView("overlay");
$("edit").onclick = () => editBed(!state.editing); $("finish-edit").onclick = () => editBed(false);
for (const id of ["orientation","confirmed","nadir"]) $(id).onchange = () => { if (id === "orientation") $("confirmed").checked = false; updateTable(); resetResult(); draw(); };
$("download-json").onclick = () => download(new Blob([JSON.stringify(state.result.event,null,2)],{type:"application/json"}),"positioning-event.json");
$("download-image").onclick = () => { const link = document.createElement("a"); link.href = `data:image/jpeg;base64,${state.result.annotation}`; link.download = "bed-assessment.jpg"; link.click(); };
$("sample").onchange = async () => { if ($("sample").value === "") return; const sampleId = $("sample").value; const item = state.settings.samples.find((sample) => String(sample.id) === sampleId); setError(); try { const response = await fetch(`/api/sample/${sampleId}`); if (!response.ok) throw new Error("Sample image is unavailable."); await loadBlob(await response.blob(),item.name); } catch (error) { setError(error.message); } };
new ResizeObserver(draw).observe($("canvas"));
async function initialize() {
  icons();
  try {
    const response = await fetch("/api/settings"); if (!response.ok) throw new Error("Local settings are unavailable.");
    state.settings = await response.json();
    for (const profile of state.settings.profiles) $("profile").append(new Option(profile.label,profile.id));
    for (const sample of state.settings.samples) $("sample").append(new Option(sample.name,sample.id));
    applyProfile();
    if (state.settings.samples.length) { const initial = state.settings.samples[Math.min(6,state.settings.samples.length-1)]; $("sample").value = String(initial.id); $("sample").dispatchEvent(new Event("change")); }
  } catch (error) { setError(error.message || "Unable to connect to the local server."); }
}
initialize();