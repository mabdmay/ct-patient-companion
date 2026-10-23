"""The patient's journey: waiting room -> identification -> changing room -> CT bed -> done.

Most stages advance automatically after `duration` seconds (hackathon demo choice: a mostly
scripted, hands-off timeline - see runner.py) or on a UI "Next" click in manual mode. One
exception: "waiting_room_call" (kind "call_and_wait") always blocks on actually recognizing
the patient's face, regardless of timer/manual mode - that one's an explicit request, not a
timed step. Live sensor results from face_client and pose_bridge are computed and shown
during every camera-using stage; elsewhere they just shape the displayed/spoken text.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    id: str
    title: str
    duration: float
    kind: str  # "call_and_wait" | "identify" | "track" | "static" | "examples" | "pose_loop"


STAGES = [
    Stage("waiting_room_call", "Waiting room", 6, "call_and_wait"),
    Stage("greet", "Greeting", 5, "static"),
    Stage("guide_changing_room", "Guiding to changing room", 8, "track"),
    Stage("confirm_at_changing_room", "Confirming at the door", 5, "identify"),
    Stage("changing_room_wait", "Waiting while changing", 12, "static"),
    Stage("confirm_after_changing", "Confirming on return", 5, "identify"),
    Stage("guide_ct_room", "Guiding to CT room", 8, "track"),
    Stage("posture_instructions", "Positioning instructions", 8, "examples"),
    Stage("pose_monitoring", "Checking position", 18, "pose_loop"),
    Stage("scanning", "Scanning", 8, "static"),
    Stage("scan_complete", "Scan complete", 5, "static"),
    Stage("return_waiting_room", "Returning", 8, "static"),
    Stage("done", "Journey complete", 5, "static"),
]


def render_message(stage: Stage, state, config) -> str:
    name = state.detected_name or config.DEMO_PATIENT_NAME
    if stage.id == "waiting_room_call":
        return f"{config.DEMO_PATIENT_NAME}? {config.DEMO_PATIENT_NAME}, it's time for your CT scan. I'm coming to get you."
    if stage.id == "greet":
        return f"Hi {name}, I am your CT companion Olaf. Please follow me."
    if stage.id == "guide_changing_room":
        return "Please follow me to the changing room."
    if stage.id == "confirm_at_changing_room":
        return "Let me just check it's still you..."
    if stage.id == "changing_room_wait":
        return "Please go inside and change into your scan clothing. I'll wait right here."
    if stage.id == "confirm_after_changing":
        return "Welcome back! Let me just check it's still you..."
    if stage.id == "guide_ct_room":
        return "Great, follow me - we're heading to the CT scan room now."
    if stage.id == "posture_instructions":
        return "Please lie down on the bed like the example shown, within the marked area."
    if stage.id == "pose_monitoring":
        return "Hold still while I check your position."
    if stage.id == "scanning":
        return "Great positioning! Please remain still - the scan is starting now."
    if stage.id == "scan_complete":
        return "All done! You can get up now."
    if stage.id == "return_waiting_room":
        return "Please follow me back to the waiting room."
    if stage.id == "done":
        return "Thank you! See you next time."
    return ""
