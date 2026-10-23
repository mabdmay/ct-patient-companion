# Patient Journey Script — CT Scan Robot Interaction

**Robot name:** [TBD]
**Context:** Outpatient CT scan appointment. Robot handles reception, navigation, preparation check, patient positioning guidance, and farewell.

---

## Phase 1 — Calling the Patient (Waiting Room)

*Robot is in the waiting room. System has the next patient's name from the appointment list.*

**ROBOT (screen shows patient name, speaks clearly across the room):**
"Mr. Müller?"

*Waits 3–5 seconds. No response.*

**ROBOT:**
"Mr. Müller?"

*Waits 3–5 seconds. Patient stands up and approaches. Face recognition confirms identity.*

**ROBOT:**
"Hi Mr. Müller, it's nice to meet you. I'll assist you with your CT scan today. Please follow me to the changing room."

*Robot begins navigating.*

---

## Phase 2 — At the Changing Room

*Robot arrives at changing room, turns to patient.*

**ROBOT:**
"Here's the changing room. If you're wearing any metal — a belt, jewelry, a watch, anything like that — please leave them in here. You'll also find CT clothes inside to change into. Take your time, I'll wait right here."

*Robot waits outside.*

---

## Phase 3 — Patient Comes Out of Changing Room

*Patient exits the changing room.*

**ROBOT:**
"All good? Ready for the scan?"

*Robot's vision module checks whether the patient has changed into the CT gown/clothes.*

### If patient HAS changed:

**ROBOT:**
"Great, let's go. Follow me to the CT room."

*Robot begins navigating to CT room.*

### If patient has NOT changed:

**ROBOT:**
"Uhh, I think you didn't change into the CT clothes. That's required before we move on. Please find them in the room — I'll wait right here."

*Robot waits. Patient goes back in and changes. Comes back out.*

**ROBOT:**
"Perfect. Let's go. Follow me to the CT room."

*Robot begins navigating.*

---

## Phase 4 — At the CT Table

*Robot arrives at the CT scan room, positions near the bed.*

*Screen displays reference images showing the correct lying position on the CT bed.*

**ROBOT:**
"Okay ... so, please lay on the bed when you're ready. You can see my screen for the ideal position. I'll guide you if something doesn't look right."

*Robot waits 8–10 seconds for patient to get on the bed and settle.*

---

### Pose Check

*Robot's vision module evaluates the patient's positioning.*

### If pose is GOOD:

**ROBOT:**
"OK, everything looks good. Please relax and stay still. It'll only take a moment."

### If pose needs correction:

**ROBOT:**
"Hmm, please put your arms to the sides and tuck your legs in."

*Waits for patient to adjust.*

**ROBOT:**
"Alright, great. Please relax and stay still. It'll only take a moment."

*Scan begins.*

---

## Phase 5 — Scan Complete

*Scan finishes. Robot addresses the patient.*

**ROBOT:**
"Alright ... we're done here now. Please get off the bed. Let's go back!"

*Robot waits for patient to get up, then begins navigating back toward the changing room and waiting area.*

---

## Phase 6 — Farewell (Near Waiting Room)

*Robot arrives near the waiting room.*

**ROBOT:**
"Thank you for coming in. I wish you a nice day!"

*Robot returns to station. Loop starts over — robot picks up the next patient from the appointment list.*

---

## Design Notes

### Tone
- Brief and natural. Not chatty, not clinical.
- Light personality (the "uhh" and pauses make it feel human, not scripted).
- Uses the patient's name once at greeting, doesn't overuse it.

### Key Technical Triggers
| Moment | Trigger |
|---|---|
| Calling patient name | Appointment list / schedule system |
| Confirming identity | Face recognition on approach |
| Repeating name call | 3–5 second timer, loop until face match |
| Clothing check | Vision module after patient exits changing room |
| Pose check | Vision module at CT bed, 8–10 second delay |
| Scan complete signal | Technologist trigger / system callback |
| Loop restart | Robot returns to waiting room, pulls next appointment |

### Adaptive Edge Cases
- **Face not recognized:** "I'm sorry, I didn't catch that. Could you come a bit closer?"
- **Patient takes long in changing room:** Robot stays silent and waits. No nagging.
- **Pose can't be corrected after two attempts:** "Let me call the technologist to help you get comfortable." (Hand off to human.)
- **No more appointments:** Robot returns to idle/cruising mode.
