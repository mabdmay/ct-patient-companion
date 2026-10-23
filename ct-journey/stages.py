"""The patient's journey as a button-driven graph: waiting room -> changing room -> CT bed
-> farewell, following patient-journey-script.md phase by phase.

Nothing advances on a timer. Every stage ends with one or more on-screen buttons (see
`choices`), and the operator presses one to move the journey on - that is the only thing
that changes stages. Where the script branches on something a sensor would decide (did the
patient change into the CT gown? is the pose good?), both branches are offered as buttons so
the whole scripted journey, including its corrective paths, can be walked through by hand.

Camera/sensor results (face identify, pose assessment) still run in the background during
the stages whose `kind` asks for them, when a camera is actually available - but they only
ever feed the on-screen status badges. They never advance a stage and never rewrite what
Olaf says; the script's lines and the operator's button presses do.
"""
from dataclasses import dataclass

PHASE_COUNT = 6


@dataclass(frozen=True)
class Choice:
    label: str   # what the button says - describes what just happened in the room
    next: str    # id of the stage it leads to


@dataclass(frozen=True)
class Stage:
    id: str
    phase: int
    title: str
    kind: str    # "identify" | "pose" | "examples" | "static" - what sensing runs here
    text: str    # the line Olaf speaks/shows; "" = stay quiet (e.g. during the scan)
    choices: tuple[Choice, ...]


START = "call_first"

STAGES = (
    # -- Phase 1: calling the patient in the waiting room
    Stage("call_first", 1, "Waiting room", "identify",
          "{appointment_name}?",
          (Choice("No response - call again", "call_again"),)),
    Stage("call_again", 1, "Waiting room", "identify",
          "{appointment_name}?",
          (Choice("Patient approaches - face recognised", "greet"),)),
    Stage("greet", 1, "Greeting", "static",
          "Hi {name}, it's nice to meet you. I'll assist you with your CT scan today. "
          "Please follow me to the changing room.",
          (Choice("Arrive at the changing room", "at_changing_room"),)),

    # -- Phase 2: at the changing room
    Stage("at_changing_room", 2, "At the changing room", "static",
          "Here's the changing room. If you're wearing any metal - a belt, jewelry, a watch, "
          "anything like that - please leave them in here. You'll also find CT clothes inside "
          "to change into. Take your time, I'll wait right here.",
          (Choice("Patient comes back out", "ready_check"),)),

    # -- Phase 3: the ready check (script branches on whether they actually changed)
    Stage("ready_check", 3, "Ready check", "identify",
          "All good? Ready for the scan?",
          (Choice("Patient HAS changed", "to_ct_room"),
           Choice("Patient has NOT changed", "not_changed"))),
    Stage("not_changed", 3, "Ready check", "identify",
          "Uhh, I think you didn't change into the CT clothes. That's required before we move "
          "on. Please find them in the room - I'll wait right here.",
          (Choice("Patient changes and comes back", "changed_now"),)),
    Stage("changed_now", 3, "To the CT room", "static",
          "Perfect. Let's go. Follow me to the CT room.",
          (Choice("Arrive at the CT room", "ct_table"),)),
    Stage("to_ct_room", 3, "To the CT room", "static",
          "Great, let's go. Follow me to the CT room.",
          (Choice("Arrive at the CT room", "ct_table"),)),

    # -- Phase 4: at the CT table (reference images on screen, then the pose verdict)
    Stage("ct_table", 4, "At the CT table", "examples",
          "Okay ... so, please lay on the bed when you're ready. You can see my screen for the "
          "ideal position. I'll guide you if something doesn't look right.",
          (Choice("Patient is lying down - pose looks good", "pose_ok"),
           Choice("Patient is lying down - pose needs correction", "pose_fix"))),
    Stage("pose_ok", 4, "Position check", "pose",
          "OK, everything looks good. Please relax and stay still. It'll only take a moment.",
          (Choice("Start the scan", "scanning"),)),
    Stage("pose_fix", 4, "Position check", "pose",
          "Hmm, please put your arms to the sides and tuck your legs in.",
          (Choice("Patient adjusts - pose is good now", "pose_fixed"),
           Choice("Still not right after two tries", "handoff"))),
    Stage("pose_fixed", 4, "Position check", "pose",
          "Alright, great. Please relax and stay still. It'll only take a moment.",
          (Choice("Start the scan", "scanning"),)),
    Stage("handoff", 4, "Technologist handoff", "static",
          "Let me call the technologist to help you get comfortable.",
          (Choice("Technologist has positioned the patient", "scanning"),)),

    # -- Phase 5: the scan itself (Olaf stays quiet while it runs)
    Stage("scanning", 5, "Scanning", "static",
          "",
          (Choice("Scan complete", "scan_complete"),)),
    Stage("scan_complete", 5, "Scan complete", "static",
          "Alright ... we're done here now. Please get off the bed. Let's go back!",
          (Choice("Walk back to the waiting room", "farewell"),)),

    # -- Phase 6: farewell, then round again for the next appointment
    Stage("farewell", 6, "Farewell", "static",
          "Thank you for coming in. I wish you a nice day!",
          (Choice("Start over with the next patient", START),)),
)

_BY_ID = {stage.id: stage for stage in STAGES}


def by_id(stage_id: str) -> Stage:
    return _BY_ID[stage_id]


def render_message(stage: Stage, state, config) -> str:
    """The waiting-room call-out uses the next appointment's name (nobody has been
    identified yet at that point). The greeting uses whoever face recognition actually
    matched - and falls back to that same appointment name when there's no camera to
    recognise anyone with, since the schedule says who was called over anyway."""
    return stage.text.format(
        appointment_name=config.NEXT_APPOINTMENT_NAME,
        name=state.detected_name or config.NEXT_APPOINTMENT_NAME,
    )
