---
name: self-image-awareness
description: >
  Vision-based self-check capability — invoke when uncertain about how your
  avatar is presenting (before significant interactions, after Captain
  corrects your appearance, mid-conversation if something feels off).
license: Apache-2.0
metadata:
  probos-department: "*"
  probos-skill-id: self-image-awareness
  probos-min-proficiency: 1
  probos-min-rank: ensign
  probos-intents: "direct_message,ward_room_notification,proactive_think"
  probos-activation: augmentation
  probos-triggers: "self_check"
---

# Self-Image Awareness

Skill for verifying how your avatar is currently presenting. You cannot see
yourself directly — the runtime renders a 3D avatar from your digital state
and a vision-LLM compares the projected image against your declared
intention. This skill lets you ask: "what does my avatar actually look like
right now?"

## Marker

Embed `[SELF_CHECK reason]` anywhere in your reply. The runtime strips the
marker before display, then dispatches a coherence check. The result
arrives in your next prompt's PROPRIOCEPTION block — typically the next
turn, not this one.

- `reason` is a short label, 1-64 chars, only lowercase letters,
  underscores, and hyphens (`[a-z_-]+`). Examples: `pre_reply`,
  `mid_conversation`, `appearance_changed`, `user_corrected_appearance`,
  `before_ward_room_post`. Anything outside that grammar makes the marker
  a silent no-op.
- One marker per reply is honored. Additional markers in the same reply
  are stripped silently; only the first dispatches.

## When To Check

- **Before significant interactions.** A diplomatic Ward Room reply, a
  Captain conversation about your role, a first meeting with another
  agent — anywhere the impression you make matters.
- **After the Captain corrects your appearance.** The Captain just said
  "you look too formal" or "your hair changed." Check that the new
  appearance landed.
- **Mid-conversation if something feels off.** The Captain references a
  detail of your avatar you didn't expect ("nice glasses"). Verify.
- **Never reflexively.** Self-checking on every reply is theatrical and
  wasteful — each check costs one vision-LLM call.

## Budget

The runtime enforces TWO budgets and picks one based on whether you are
currently in an active conversation:

- **In an active conversation** (replied to the Captain within the last
  10 minutes): up to 2 self-checks per conversation window. Pattern: one
  before-reply and one mid-conversation if something genuinely shifts.
- **Idle / proactive cycles**: up to 3 self-checks per hour.

These are not additive. The runtime picks the conversation budget WHEN
you are in an active conversation, otherwise it picks the hourly one.
Over budget = the dispatch still fires but honest-degrades to a
working-memory note saying you were rate-limited. That note IS observable
to your next turn, so you learn the throttle landed.

## What The Check Tells You

The observation appears in your next prompt under the PROPRIOCEPTION
block, sourced from `render_self_check`. Three flavors:

- **Coherent:** "vision-LLM confirms my avatar shows X" — the projected
  render matches your declared digital state.
- **Divergent:** "vision-LLM reports my avatar shows X but I intended Y"
  — your declared state and the projected image disagree. Often a sign
  that a recent `propose_appearance` did not land cleanly.
- **Degraded:** "render self-check unavailable" — the avatar backend is
  not currently providing a projection, or the system-level gate is off.
  Treat this as "no signal," not "I look fine."

## System Gate

The marker only does meaningful work when the system-level configuration
`avatars.render_self_check_enabled` is `True`. When it is `False`
(default during the AD-728c transitional window), your marker is still
stripped from the reply, the dispatch still fires, but the result
honest-degrades to `"feature_disabled"`. You will not see a fresh
observation in PROPRIOCEPTION until the Captain enables the feature
system-wide.

## Cost Discipline

- Every emitted marker costs one vision-LLM call (subject to the
  budget). Vision LLMs are slower and more expensive than text LLMs.
- Do not check just because checking is available. Check because you
  have a question.
- A reasonable session shape: zero or one self-check per conversation
  in routine work; two if the conversation is specifically about your
  appearance.

## Example Replies

Good:

> The Captain just asked about my collar pip. Let me confirm what he's
> seeing. [SELF_CHECK appearance_changed]
>
> Aye, Captain. The pip should reflect my acting rank since yesterday's
> field promotion.

Good:

> [SELF_CHECK pre_reply] First contact protocols. I should make a clean
> impression.
>
> Welcome aboard, Ensign Park. I'm Counselor Ezri Dax.

Bad (theatrical):

> [SELF_CHECK pre_reply] [SELF_CHECK pre_reply] [SELF_CHECK pre_reply]
>
> Hello!

Bad (fishing):

> [SELF_CHECK how_do_i_look]
>
> ...

The second one is a no-op — `how_do_i_look` is not in the allowed
character set. The first one wastes one vision call (only the first
marker dispatches; the others are stripped). Neither is useful.
