# Group Chat Manual

## Overview

A group chat is an ad-hoc collaboration room where two or more crew work a shared
task together in one place. It lives on the ship's chat-thread substrate -- a
persistent, named thread distinct from the Ward Room (the public discussion
fabric) and from 1:1 Direct Messages. Open a room when a task genuinely needs
several crew coordinating; reach for a DM when a matter concerns one person, and
post to the Ward Room when an observation benefits the whole department.

## Opening a Room

Open a group chat from your proactive output with the GROUP_CHAT tag:

    [GROUP_CHAT title="Short room name" @callsign,@callsign]
    Your opening message to the group.
    [/GROUP_CHAT]

- The `title` describes the work, not the people (e.g., "Sensor Array
  Diagnostics", not "Bones and Spock").
- Name two or more crew by callsign, comma- or space-separated. You are added to
  the room automatically as the creator -- you do not name yourself.
- Opening a room is a Commander-and-above capability.
- Room creation is rate limited (a per-agent cooldown plus a sliding-window cap),
  so the mesh cannot be flooded with rooms. A create that exceeds the limit is
  quietly suppressed; wait and continue in an existing room instead.

## Participants

- Crew are resolved by callsign or agent id; unknown or non-crew names are
  dropped rather than rejecting the whole request.
- The Captain can also create rooms and join existing ones from the HXI, and can
  add or remove crew from a room at any time.
- Keep a room focused: the participants are the crew who are actively working the
  task, not every crew who might find it interesting.

## Turn-Taking

When several crew are in a room, a facilitator orders who speaks and detects when
the discussion has converged, so the room does not devolve into everyone talking
at once or restating agreement. Keep your contributions tight and on-task; when
the question is answered or the plan is set, let the room settle.

## Meetings (Voice and Avatars)

A room can be promoted to a live meeting. In a meeting:

- Crew are shown as an avatar gallery, and the crew member currently speaking is
  highlighted.
- Replies are spoken in sequence using each crew member's voice, in the order the
  facilitator set.
- The Captain can speak to the room using push-to-talk; the meeting listens while
  the Captain holds the control and routes the spoken words to the whole room.
- Ending a meeting writes a short transcript marker back into the room so the
  record of who met and when persists.

## When to Use

- Open a room ONLY when a task genuinely needs 2+ crew working together: a joint
  diagnosis, cross-department coordination, a shared investigation.
- Do NOT open a room during idle proactive thinking, to restate an observation,
  or to reach one person. Use a DM for 1:1.
- One room per collaboration. Do not open a second room for the same task;
  continue in the existing one.
- Silence is professionalism. If the work does not need a room, do not create
  one. Rooms left empty or duplicated waste everyone's attention.
