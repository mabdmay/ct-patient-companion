# CT Patient Journey - orchestrator

Wires together the two existing hackathon repos into one scripted patient journey, from the
waiting room to the end of the scan, plus the on-screen UI the robot shows at each step.

```
waiting room          changing room                     CT room
   |                        |                               |
calls name --> detects --> guides --> confirms --> waits --> confirms --> guides --> posture
   face         approach    there      same          while    same         there      instructions
   (patient_id)                        patient       changing  patient                  (examples)
                                                                                           |
                                                                                    lies on bed
                                                                                           |
                                                                          pose_monitoring (positioning repo,
                                                                          ceiling camera, live corrections)
                                                                                           |
                                                                    scanning --> complete --> returns to waiting room
```

## Components

| Part | Repo | How it's used |
|---|---|---|
| Face recognition + continuous tracking | `patient-face-id-robot` | Run unmodified as its own HTTP service (`patient_id.service`), owning the robot-facing camera. This project calls it over REST (`face_client.py`), the way a real ACU Gateway would. |
| Pose / positioning on the CT bed | `hackathon-...-742` (CT_Patient_Positioning) | Imported as a Python library (`pose_bridge.py`), unmodified. Owns the ceiling camera directly; runs `assess_position` each frame during the `pose_monitoring` stage. |
| On-screen UI | `web/` + `server.py` | A small local web page the robot's screen browser opens; shows the current instruction, live tracking/posture badges, both camera previews, and speaks each new instruction with the browser's offline text-to-speech. |
| Journey orchestrator | `stages.py`, `runner.py`, `state.py`, `run.py` | The state machine: an ordered list of stages, each with a duration and a "kind" (what sensor, if any, runs during it). Advances on a fixed timer per stage (chosen so the demo is fully hands-off and doesn't depend on live detection succeeding) while still computing and displaying real face-id/posture results throughout. |

## Running it

Two cameras are expected: one facing the patient (robot's "face"), one overhead on the CT
bed (ceiling camera). Find their indices first (0, 1, 2, ... - try `--face-camera`/
`--pose-camera` combinations if the picture is wrong).

```powershell
cd ..\patient-face-id-robot
python -m patient_id.enroll --from-reference-images   # once, if not already enrolled

cd ..\ct-journey
pip install -r requirements.txt
python run.py --face-camera 1 --pose-camera 0
```

Open http://127.0.0.1:8090 in a browser (ideally the one that will sit on the robot's
screen). Click anywhere on the page once - browsers require a user gesture before
speech synthesis is allowed to play audio.

`--no-face-service` skips starting `patient_id.service` if you already have it running
(e.g. you started it by hand to watch its own logs).

## What's real vs. scripted

- **Real, computed live:** face detection/recognition at the approach and changing-room
  checkpoints, continuous "is the patient still following" tracking (`patient_id`'s
  tracker), and the posture assessment during `pose_monitoring` (YOLO pose + the
  positioning repo's geometry/arm rules) - all shown in the UI as it happens.
- **Scripted:** stage *transitions* are time-based, not gated on any of the above
  succeeding. There's no real robot movement, door sensor, or changing-room sensor in a
  laptop demo, so every stage (sensed or not) advances after a fixed duration
  (`stages.py`). This was a deliberate choice for a reliable, repeatable demo - see
  `journey_config.py` to tune durations, and `runner.py` if you want to gate specific
  transitions on sensor confirmation instead.

## Known placeholders (carried over honestly, not hidden)

- `DEMO_PATIENT_ID` / `DEMO_PATIENT_NAME` in `journey_config.py` stand in for "today's
  worklist" - a real deployment would get the expected patient from the ACU schedule.
- `pose_bridge.py`'s `TABLE_CORNERS` treats the *whole ceiling-camera frame* as the table,
  so the demo runs on any camera angle. A production system must replace this with a real
  surveyed bed calibration (positioning repo README, "Table Setup").
- Advisory only: as in both source repos, nothing here authorizes scanning or controls the
  scanner. `pose_monitoring`'s correction messages are suggestions, not interlocks.
