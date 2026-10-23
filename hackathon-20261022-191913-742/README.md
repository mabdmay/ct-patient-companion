# CT Patient Positioning: Phase 1

Local, advisory 2D positioning prototype for the Siemens Healthineers Robotics & AI Hackathon 2026. Implements the Phase 1 geometry and capture path from the supplied technical solution document. No training, cloud inference, patient identification, or scanner control.

**Not a medical device. `WITHIN_CRITERIA` means only that configured, visible 2D torso and enabled arm checks passed on this frame. It does not authorize scanning, establish clinical positioning, or establish patient stability. All thresholds are demonstration placeholders. Leg posture is not assessed.**

## Phase 1 Scope

- Read a static image, directory of images, prerecorded video, or numeric webcam device.
- Use pretrained Ultralytics YOLO26 nano pose and COCO shoulders/hips.
- Mask all pixels outside the bed before inference and map an upright bed view back to original image coordinates.
- Define a table polygon and longitudinal centerline; compare with a configurable reference.
- Estimate torso center, lateral displacement, and undirected body-axis error. Optional longitudinal check when a reference is provided.
- Describe visible arm posture using shoulders, elbows and wrists, with optional protocol-specific allowed postures.
- Render landmarks, torso axis/center, centerline, reference line, lateral tolerance boundaries, reasons, and status.
- Emit per-frame advisory JSON and measure inference/processing latency.
- Supply a deterministic synthetic demonstration and automated geometry/pipeline tests.

**Not yet implemented:** temporal landmark tracking, baseline confirmation, sustained-motion detection, smoothing, hysteresis, camera-shake compensation, segmentation, or robot/scanner commands. Those belong to Phases 2 and 3. The optional local HTTP image-review UI below does not add monitoring or scanner-control capability.

## Local Image Review UI

```powershell
.\venv\Scripts\python.exe ui.py
```

Open http://127.0.0.1:8765. If the port is occupied, the server selects another of the next nine ports and logs the actual address. No additional Python dependencies or frontend build are required.

- Paste an image into the page, use the clipboard/upload buttons, drop a file into the image area, or select a supplied sample.
- Select the camera reference and arm policy, then click **Analyze image**.
- Inspect the bed-only landmark overlay, status/reasons, lateral offset, axis error, arm posture, model score, inference timing, and JSON event.
- Download the annotated bed image or JSON event using the download controls.
- For a different camera framing, use **Edit bed rectangle**, drag across the bed, choose the head end, and confirm the near-overhead rectangular view and bed reference. Editing the region removes confirmation; unconfirmed geometry remains uncertain. This editor is image-plane only, not a metric calibration tool.

The supplied-camera preset is a demonstration reference for the supplied photos, not a clinical calibration. A new crop or camera angle needs a new checked bed region. A changed image, policy, or reference clears the previous decision. The UI uses the same pose, confidence, geometry, and arm-policy code as the CLI, caching the local model between requests. First analysis can take several seconds.

Images are processed locally in memory and are not automatically saved. Only explicit downloads create result files in your browser. Limits: 12 MB per image and 20 megapixels. Use consented data and nonidentifying filenames. The UI server listens on loopback only, restricts cross-origin access, and is for local hackathon use, not public deployment. Icons are bundled locally (Lucide 0.468.0; license in web/lucide.LICENSE); no CDN, external fonts, or cloud inference is used at runtime.

Verification for this addition was deliberately focused: JavaScript syntax, four service checks, and one live HTTP smoke request with a supplied chest-folded photo (reposition required, over-torso arms, valid annotation). The existing full test suite was not rerun. Managed Edge policy blocked automated browser/headless checks; visual desktop/mobile layout, native clipboard permissions, and browser downloads still require manual verification.

## Installation

Python 3.10+ is the source target. The current workspace was exercised using its existing Python 3.13 environment. Create an environment if needed; do not replace an existing one:

```powershell
py -3.13 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Use your installed Python version in place of `-3.13`. If PyTorch does not provide wheels for that version/platform, use Python 3.10-3.12 and a compatible PyTorch installation. A GPU is optional; CPU is the default. OpenCV requires a desktop session for windows; use `--no-display` for headless operation.

Download the public pretrained weights once, from the project root (network access required for this step only):

```powershell
.\venv\Scripts\python.exe -c "from ultralytics import YOLO; YOLO('yolo26n-pose.pt')"
```

Alternatively copy a trusted `yolo26n-pose.pt` file into this directory. The application itself checks for local weights before loading and does not initiate a model download. Relative weight paths resolve against the configuration directory. Review the Ultralytics/model license before redistribution or use beyond the hackathon. Do not load untrusted PyTorch model files.

Tested locally: Ultralytics 8.4.183, OpenCV 4.14.0.94, NumPy 2.5.4, PyYAML 6.0.3, PyTorch 2.14.1, Python 3.13.1. Dependency ranges are in requirements.txt; exact versions on another platform can differ.

## Immediate Demo

No camera, weights, or downloads are needed for the synthetic path after core dependencies are installed:

```powershell
.\venv\Scripts\python.exe main.py --demo
.\venv\Scripts\python.exe main.py --demo --no-display --output outputs/demo.avi --jsonl outputs/demo.jsonl
.\venv\Scripts\python.exe -m examples.generate_demo
```

The 120-frame demo contains six 20-frame cases: centered, shifted, rotated, occluded, empty, and ambiguous. It injects known keypoints; it is **not a test of model perception**. The overlay and events explicitly label this. Default expected statuses: within criteria, reposition, reposition, uncertain, uncertain, uncertain. The demo replaces table geometry with its synthetic geometry but retains configured reference rules and thresholds.

The generator creates raw and annotated PNGs, a raw AVI, a synthetic configuration, and expected JSON events under examples/generated/. For instance, open examples/generated/centered_annotated.png. Generated images depict a schematic mannequin, not a real person. Passing them through YOLO may find no person; that is a perception smoke test, not an accuracy evaluation.

## Real Input

First configure the actual table and confirm the geometry as described below, then use consented or synthetic data only:

```powershell
# One image: shows a window until a key is pressed; optionally save annotation.
.\venv\Scripts\python.exe main.py --source data/consented_overhead.png --output outputs/annotated.png

# Replay video. q or Escape stops the display.
.\venv\Scripts\python.exe main.py --source data/consented_clip.mp4 --jsonl outputs/events.jsonl

# USB camera, limited run; use --source 1 for another device.
.\venv\Scripts\python.exe main.py --source 0 --max-frames 300

# Offline model smoke test using generated empty-table input.
.\venv\Scripts\python.exe main.py --config examples/generated/synthetic_config.yaml --source examples/generated/empty.png --no-display --output outputs/empty_yolo.png
```

JSON events go to stdout; logging and timing summaries go to stderr. Use `--jsonl` for a dedicated event file. `--output` saves an annotated image, `.avi`/`.mp4`, or numbered PNGs when given a directory path without a suffix. A still-image destination keeps only the last processed frame. Output files are overwritten. No input images/video are stored by default. Events contain numerical geometry and the input filename, not images; use nonidentifying filenames. Annotations are masked and cropped to the bed region.

Video input is processed in order, not at a guaranteed real-time rate. Source timestamps are nominal frame-index/FPS values; UTC timestamps mark acquisition into this pipeline. Saved video's FPS follows the source (10 FPS for the demo), not inference throughput. FPS and alert latency must be benchmarked on target hardware. No capture queue or inference-skipping tracker is included yet.

## Supplied Photo Set: Bed-Only Review

config.data.yaml contains a manually selected image-plane demo ROI for the horizontal bed in the supplied 1920x1080 images. Its corners correspond approximately to x=390..1460, y=435..725. Table-coordinate head/top is at image left. `confirmed: true` and `near_nadir: true` in this **demonstration preset** record a visually selected rectangular ROI and near-overhead assumption, not a surveyed calibration or clinical approval. It has no centimeter measurements. Do not reuse it after camera movement or for a different view; the last supplied photo does not show the same table view and returns uncertain.

Only bed pixels reach YOLO. Outside staff are masked, and confident torso centers outside the polygon are excluded even if their boxes overlap it. More than one remaining bed candidate is still uncertain. A person leaning into the bed region can remain ambiguous; no identity tracking is used. Arms outside the selected bed are deliberately not inferred as visible.

```powershell
# Process all supplied images and save one bed-only annotation per photo.
.\venv\Scripts\python.exe main.py --config config.data.yaml --source data --no-display --output outputs/data_review --jsonl outputs/data_review.jsonl

# Generate a contact sheet, CSV and numerical summary from that run.
.\venv\Scripts\python.exe -m examples.summarize_photos

# Inspect a chest-folded photo under the demonstration alongside-only policy.
.\venv\Scripts\python.exe main.py --config config.data.yaml --source data/WIN_20261022_17_29_23_Pro.jpg

# Explicitly allow OVER_TORSO instead; same image then passes the enabled 2D rules.
.\venv\Scripts\python.exe main.py --config config.data.yaml --source data/WIN_20261022_17_29_23_Pro.jpg --allowed-arms OVER_TORSO
```

Outputs: outputs/data_review_contact_sheet.jpg, outputs/data_review.csv, outputs/data_review_summary.json and individual outputs/data_review/0000.png etc. `frame_index` and `source_file` connect each annotation to its source. Data and generated outputs are excluded from Git by default. Use only consented demonstration images and secure the local output directory.

The preset permits `ALONGSIDE_BODY` only as an example protocol. Choose the permitted arm posture with clinical/hackathon guidance; chest-folded arms are not inherently wrong for every examination. `--allowed-arms ARMS_RAISED ALONGSIDE_BODY` permits either bilateral posture. `MIXED` is only allowed when explicitly included. The configuration's `arms.allowed_postures: null` disables arm gating while still reporting an observation.

## Arm Posture Rules

positioning/arms.py uses a body-relative coordinate system: longitudinal distances are fractions of shoulder-to-hip midpoint length; lateral distances are fractions of projected shoulder width. This makes the rules invariant to image rotation, translation and uniform scaling, but not immune to perspective or parallax.

- `OVER_TORSO`: wrists project within the inner shoulder span and torso length, with forearms bending back or inward relative to elbows. Includes arms folded across chest/upper torso; does not prove physical chest contact or distinguish chest from abdomen precisely.
- `ARMS_RAISED`: wrists are headward of the shoulders and elbows are sufficiently headward.
- `ALONGSIDE_BODY`: wrists are sufficiently footward and lateral to the torso midline.
- `MIXED`: the two arms have different recognized postures.
- `UNCERTAIN`: missing/low-confidence joints, implausible projected limbs, insufficient shoulder width, or a pose not covered by these rules.

All required arm/torso joints must meet `arms.min_confidence`; a high model confidence alone cannot override geometric uncertainty. A required unobservable arm rule makes the overall status uncertain, even if torso checks passed. A recognized posture outside the allowed set gives `arm_posture_not_allowed` and reposition-required unless another required check is unobservable. Arm geometry thresholds are configurable under `arms` in YAML. The default confidence is 0.5; the torso wrist lateral limit is 0.45 shoulder widths, and the raised wrist margin is 0.15 torso lengths. Thresholds were adjusted using the supplied development photos, not independently validated.

Leg spread, knee bend, side-lying and supine/prone posture are **not** classified. Some supplied images with spread legs pass the configured torso/arm criteria. This is expected under the current rule set, not a claim that those full-body postures are clinically correct. Low-confidence wrist/arm cases and rolled-body examples remain uncertain. Assess arms raised beyond the bed only after explicitly defining an allowed observation region; this strict bed-only version cannot see outside it.

## Table Setup

The distributed config.yaml is intentionally **unconfirmed**, so real input returns `UNCERTAIN` until the setup is checked. The displayed polygon can be used to inspect alignment before enabling evaluation.

1. Fix the camera. Obtain an empty-table frame with the same resolution, crop, and camera settings as runtime.
2. Set `table.corners_normalized` in TL, TR, BR, BL order. Convert each image coordinate using `x/(width-1), y/(height-1)`; corners must be a convex quadrilateral.
3. For a nearly overhead, rectangular table view, set `near_nadir: true`. Coordinates remain in pixels internally; lateral output is a fraction of table width. A skewed polygon is rejected in this mode because image-plane angles cannot be treated as table-plane angles.
4. For perspective correction, enter **measured** `[width, length]` in `dimensions_cm` for those exact four table-plane corners. A homography maps those corners to a physical rectangle. Do not infer centimeters from pixel counts. `near_nadir` is not required in this mode.
5. After a technologist/operator checks the table geometry and reference, set `confirmed: true`. Recheck after any camera movement, zoom, crop, lens change, or table-plane change.

Metric measurements are named `*_cm_projected` because they are table-plane projections, not accurate 3D body coordinates. Shoulders and hips are elevated above the table, causing parallax. Lens distortion is not estimated or corrected by this MVP; use pre-undistorted input or a suitable near-nadir, low-distortion setup. Calibration has not been validated to clinical accuracy.

Coordinates: x runs across the table from its selected left to right edge, zero at the centerline; y increases from the selected top/head edge toward the bottom/foot edge. For a rotated bed these need not match image x/y directions. This is **not necessarily anatomical patient right or head-to-feet**. Axis comparison is undirected modulo 180 degrees, so this MVP cannot distinguish head-first from feet-first. Supine/prone and lying-versus-standing are also not verified by torso geometry alone.

## Geometry And Decisions

For shoulders S=(LS+RS)/2 and hips P=(LH+RH)/2, torso center C=(S+P)/2 and axis v=P-S. All computations occur in the table coordinate system.

- `center_offset_fraction = C.x / table_width - reference.lateral_fraction`; signed, measured in table widths.
- `axis_error_deg` is the smallest undirected angle between v and `reference.axis_deg`, where 0 degrees means the positive longitudinal axis.
- If `reference.longitudinal_fraction` is non-null, `longitudinal_offset_fraction = C.y / table_length - reference.longitudinal_fraction`.
- Check absolute deviations against the configured maximum tolerances, inclusively.

Default tolerances: 0.08 table widths laterally, 8 degrees, and 0.1 table lengths longitudinally if enabled. These are software-demo values, **not clinical recommendations**. There are no hidden centimeter thresholds. Different protocols should use separate configuration files selected with `--config`; reference confirmation is an operator responsibility.

Exactly one sufficiently confident bed candidate must remain after box-intersection and confident torso-center containment filtering. Two remaining candidates return `UNCERTAIN`; the largest box is never silently selected. Outside-bed staff are masked before inference. All four shoulders/hips must have finite coordinates, confidence at least 0.5, lie inside the table, and form a nondegenerate torso axis.

- `WITHIN_CRITERIA`: every configured observable 2D rule passed on this frame.
- `REPOSITION_REQUIRED`: reliable geometry exceeded at least one configured tolerance.
- `UNCERTAIN`: unconfirmed/skewed calibration, no person, ambiguity, absent/low-confidence landmarks, invalid geometry, or input/processing failure.

On a detected camera read failure the CLI emits an uncertain failure event, releases resources, and exits nonzero. A video ending normally is EOF, not a patient-loss event. Camera-driver blocking timeouts and recovery are not guaranteed by this MVP. Never consume a stale within-criteria event as a continuing authorization.

## Architecture

```text
main.py                       CLI and frame orchestration
ui.py                         Loopback-only image-review server and analysis API
web/                          Local HTML/CSS/JavaScript image-review workspace
positioning/camera.py         Image/video/webcam input; optional annotated output
positioning/perception.py     PerceptionBackend contract and YOLO adapter
positioning/arms.py           Body-relative arm observations and protocol rules
positioning/calibration.py    Table polygon, mapping, containment, homography
positioning/geometry.py       Confidence gates, patient association, 2D rules
positioning/types.py          Shared detections, rules, statuses, assessment
positioning/config.py         YAML loading and validation
positioning/visualization.py  OpenCV annotation
positioning/integration.py    Pure event builder and local JSON sink
positioning/demo.py           Explicit synthetic frames and injected poses
examples/generate_demo.py     Reproducible local fixture generator
examples/summarize_photos.py  Bed-only contact sheet and numerical/CSV summaries
examples/positioning_event.json  Sample advisory event
tests/                       Unit tests and file/CLI integration tests
```

The pipeline is capture -> masked upright bed view -> backend detections mapped to source coordinates -> table mapping -> deterministic torso/arm rules -> bed-only overlay / JSON. The backend contract remains `detect(frame) -> list[PoseDetection]`: COCO-shaped keypoints plus a box and confidence. Another pose model can implement this directly. A segmentation backend can reuse capture, calibration, status, rendering, and event output, but needs an explicit silhouette measurement/assessment strategy; it must not fabricate shoulder/hip keypoints or imply equivalent confidence. Temporal monitoring will be a separate component in Phase 2, not a hidden property of current statuses.

JSON schema 0.2 adds `arm_assessment` (bilateral and per-arm posture, confidence, active allowed postures, arm-rule status/reasons and body-relative measurements). It is null if torso geometry could not be assessed. Events include timestamp, camera/reference IDs, frame/source time and filename, status, reasons, measurements, timing, assessment scope, and `advisory_only: true`. Overall confidence is the minimum torso/detection score and valid required-arm score; it is null when required arm observation is uncertain. Scores are not calibrated probabilities of correctness. Command-line arm-policy overrides are also recorded in the reference ID. integration.make_event is a plain Python interface for future callbacks; no network endpoint or CT control action is present. Consumers must reject stale events and maintain operator authorization and all scanner interlocks.

## Verification

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests cover centered/signed-offset/rotated bodies, threshold boundaries, configured references, missing/invalid landmarks, partial occlusion, missing/ambiguous people, outside-table staff with overlapping boxes, invalid calibration, metric homography, unconfirmed setup, file/folder input, annotation, strict JSON, headless CLI output, bed-mask pixel exclusion and coordinate round trips, arm rotation invariance, folded/raised/alongside/mixed arms, protocol gating, and low-confidence-arm uncertainty. No model download is required by automated tests.

Local verification: 37 automated tests passed. All 27 supplied photos were processed through real YOLO and the bed-only demo preset: 7 within criteria, 3 reposition required (folded arms), and 17 uncertain. Seven photos had alongside-body observations, three over-torso, ten uncertain arm observations, and seven no torso assessment. Three inspected chest-folded examples were rejected by the alongside-only preset; the same example passed with OVER_TORSO explicitly allowed.

On the last 27-photo batch, inference p50/p95 was approximately 76.7/179.2 ms and processing p50/p95 112.3/211.3 ms. The original full-frame/default-thread first CPU inference took 55.4 seconds; a later separate cold-start single-photo run took 6.2 seconds. Four CPU threads and the upright bed crop reduce overhead in this environment. These measurements exclude model loading and do not establish live-camera throughput or alert latency. No physical camera was tested. The summary explicitly sets `accuracy_evaluated: false`: these photos were used during development and lack independent ground-truth annotations, so result counts are not accuracy estimates.

Before claiming overhead perception quality, collect consented recumbent-patient images representative of the actual fixed camera, manually inspect landmarks, and record false-within-criteria cases and uncertainty rate by conditions such as blankets, staff, lighting, orientation, and partial occlusion. If YOLO fails, evaluate another pose model or silhouette segmentation; no accuracy/FPS claim is made here. Single RGB cannot reliably verify depth, vertical clearance, collision safety, hidden limbs, full 3D position, or clinical scan-specific posture.