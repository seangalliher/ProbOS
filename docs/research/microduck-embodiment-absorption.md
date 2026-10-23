# Microduck Embodiment Absorption

*Sean Galliher, 2026-10-23*
*Sources, read from the repository docs on 2026-10-23: the [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck) README; `docs/robot/cheatsheet.md` (`robotctl`); `docs/design/simulation.md`; and `scripts/duck-sim`. Not read: `docs/design/architecture.md`, the JSON-RPC method list in full, and the [microduck_rl](https://github.com/pollen-robotics/microduck_rl) training repo.*

## Purpose

The Captain asked how practical it would be for a ProbOS crew agent to control a small physical robot, and whether that can be tested in simulation before buying one. This note records what Microduck offers, how it would connect to ProbOS, and what ProbOS absorbs. It takes AD-1342's principle, "the harness is the body; ProbOS is the self", literally: a robot is one more body. These are technical design references only.

## What Microduck is

- **Hardware.** A biped duck about 25 cm tall and 800 g: 15 servos, a Rockchip RK3566 board, a camera (WebRTC), a depth (ToF) sensor, Bluetooth, a speaker and optional wheels ("roller mode"). Apache-2.0, about 10k stars.
- **Control.** Reinforcement-learning policies (MuJoCo plus PPO, exported to ONNX) run in a **50 Hz control loop on the robot** (`robotd`). That loop stays on the robot. Nothing in ProbOS belongs inside it.
- **One interface.** Rust daemons on the board: `robotd` (control and motor bus), `tofd` (depth), `mediad` (camera), `padd` (gamepad), `configd`, `updaterd` (signed updates with rollback) and `btd`. They share one JSON-RPC contract on Unix sockets. `robotctl`, `duckctl` (Bluetooth), the gamepad, apps and user scripts all use it.
- **Commands** (`docs/robot/cheatsheet.md`):
  - drive as a velocity intent (`vx`, `vyaw`, clamped by `pad_drive` limits);
  - run behaviours with `robotctl robot do <skill>` (built-ins such as `ground_pick` and `sit_toggle`, plus skills added from the Hugging Face Hub);
  - stop with `robot.stop` (velocity to zero, the robot keeps standing);
  - read telemetry with `robotctl monitor --json` (commanded against applied, joints, gravity vector, fall verdict, loop rate) and `robotctl health` (battery, temperatures, loop health).
  - Changing anything needs privilege (`sudo`, or an allow-list).
- **A built-in deadman.** "No intent arrived recently, velocity zeroed." If the controller goes quiet, the robot stops walking. That is a fail-safe ProbOS can rely on, not one it has to build.

## Simulation before hardware

`scripts/duck-sim` runs **the same `robotd` binary, policies, 50 Hz loop and JSON-RPC interface** against a MuJoCo body (`duck_control::sim::RemoteIo` in place of the servo bus). The design page measures the daemon at "50.0 of 50.0 Hz, 0 missed" against MuJoCo. It is a twin "with a written-down boundary", not a mock. What the simulator does:

- **Scenes.** A bare floor, or `apartment`: six rooms in 7 × 6 m, with doorways off-centre so a pose can be worked out from the duck's 45° field of view.
- **Cameras and multiple ducks.** Cameras are opt-in per duck (`DUCK_SIM_CAMERAS`), each costing about a third of a CPU core, and several ducks can run at once (`DUCK_SIM_DUCKS`).
- **Honest labelling.** A simulated duck signed in to a Hugging Face account is flagged `simulated`, "so nobody drives a duck in MuJoCo believing it is the one on the shelf".
- **Container mode.** `duck-sim boot` runs the daemons under real systemd in a container (Linux, `sudo`).

**On the Captain's machine:** the script is POSIX shell, made for Linux and macOS, so it runs under **WSL2 (Ubuntu)**, with the MuJoCo window shown through WSLg. It needs the Rust toolchain and the `microduck_rl` virtual environment for ONNX Runtime and MuJoCo. Physics is cheap at about 0.3 ms per step for four ducks.

## How it would connect to ProbOS

A small **MCP server bridge**, running beside the duck (in WSL for the simulator, or on the LAN for a robot), exposes a narrow command set and translates it to the duck's JSON-RPC:
- `walk(vx, vyaw, seconds)`, clamped below the robot's own limits; the bridge keeps sending the intent for `seconds` and then lets the deadman stop the duck;
- `stop()`;
- `do(skill)`, from an allow-list such as sit and stand;
- `snapshot()` for a camera frame, and `depth()`;
- `status()`, a summary of health and monitor data.

Crew reach it through ProbOS's MCP bridge, which already has per-agent and department grants and risk tiers. Camera frames go to the vision tiers. A crew member's turn takes seconds, which suits "walk to the ball". Balance stays the robot's job.

| Need | Microduck | ProbOS |
|---|---|---|
| Reflexes | Onboard 50 Hz RL policy | Stays out of the loop |
| High-level action | JSON-RPC: velocity intent, `robot do`, `robot.stop` | MCP bridge tool, granted to one crew member |
| Perception | Camera, ToF | Vision tiers, perception, sensorium (Northstar II) |
| Who drives | — | AD-1159 work permit: one holder, with expiry |
| Stop | Deadman, `robot.stop`, gamepad | AD-1343 stop (software), plus the robot's own deadman as the independent backstop |
| Practice | `duck-sim` | Holodeck and Ship Trials (AD-1186), with crew told it is a simulation (#1123) |
| Body identity | Robot machine-id and HF account | AD-1342 `embodiment` field: the robot as a body of a crew member |

## Absorbed

1. **The deadman pattern.** For any physical or long-running body, the body itself must stop when the controller stops sending intent. ProbOS's software stop should never be the only stop. *Owner: AD-1348 (#1630), and AD-1342 (#1582) for bodies in general.*
2. **Same binary, different body, for testing.** Microduck's simulator runs the production daemons against a simulated body. That is the standard for a ProbOS Holodeck scenario that drives an external body. *Owner: AD-1186 (#1123).*
3. **Honest labelling of simulated bodies** (`simulated` flag). This matches the Captain's trial-disclosure rule (#1123, 2026-10-20). *Owner: AD-1186.*
4. **One narrow command contract over the device's own interface,** never raw servo or privileged commands. Privileged operations (`policy add`, `relax`, updates) stay with the Captain. *Owner: AD-1348 (#1630).*

## Rejected or deferred

- **An LLM in the control loop.** Rejected. Latency is seconds against a 20 ms loop. The RL policy owns motion.
- **Crew installing policies or skills from the Hugging Face Hub** (`robotctl policy add`). Rejected for crew: it is code from an external source. It stays a Captain action with review.
- **Physical robot control now.** Deferred. It is new capability, under the Captain's new-capability pause. Simulation comes first when the pause lifts.

## Phasing (AD-1348, #1630)

1. **Simulation only.** One crew member drives `duck-sim` through the MCP bridge in the `apartment` scene, as a Holodeck trial with disclosure.
2. **Real robot, senses only.** Camera, depth and status, with no motion.
3. **Motion under a permit.** A work permit, speed and time envelopes, Captain approval at first, the deadman and a physical stop available, and a LAN-only, authenticated bridge (the BF-903 scoped-access pattern).

## Consistent with existing ProbOS principles

The spine stays outside the body. The robot's deadman, the bridge's clamps and ProbOS's permits and stop are layers outside the agent, and the agent's hands are a narrow, governed command set. Identity, memory and accountability stay with the crew member whatever body it uses.
