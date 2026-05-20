/**
 * BF-318 — Mic arbiter for the browser SpeechRecognition singleton.
 *
 * Three independent acquisition paths fight over the same browser
 * ``SpeechRecognition`` instance (``activeRecognition`` at
 * ``speechInput.ts:28``):
 *   - press-to-talk (``IntentSurface.tsx`` ``startListening``)
 *   - wake-word continuous transcript-fallback
 *     (``wakeWord.ts:_startContinuousRecognition``)
 *   - ConversationController (AD-747, consumer of this arbiter).
 *
 * VAD is NOT in the conflict surface — it opens its own
 * ``getUserMedia({audio:true})`` stream in ``voiceActivity.ts:213``
 * and is orthogonal to the SR singleton.
 *
 * The arbiter is the single source of truth for SR ownership. It
 * enforces priority ordering, supports preemption by higher-priority
 * holders, and fans ``onReleased`` notifications out to queued
 * waiters so wake-word can re-arm deterministically.
 *
 * Priority constants:
 *   - PRIORITY_PRESS_TO_TALK = 100 (explicit user intent — always wins)
 *   - PRIORITY_CONVERSATION  = 75  (AD-747 — DM-thread always-on mode)
 *   - PRIORITY_WAKE_WORD     = 50  (ambient listening — yields)
 *
 * Same-priority rule: the second request queues; no tie-break preemption.
 */

export const PRIORITY_PRESS_TO_TALK = 100;
export const PRIORITY_CONVERSATION = 75;
export const PRIORITY_WAKE_WORD = 50;

export interface AcquireOptions {
  /** Stable holder name for logs / tests (e.g. ``press_to_talk``). */
  holder: string;
  /** Higher wins. See PRIORITY_* constants. */
  priority: number;
  /** Fires when the lease becomes active (immediately for an
   *  uncontested grant; later for a queued grant). */
  onAcquired?: (lease: Lease) => void;
  /** Fires when a higher-priority acquire preempts this lease. The
   *  preempted holder's lease is invalidated; ``release()`` on the
   *  stale lease becomes a no-op. */
  onPreempted?: (by: string) => void;
  /** Fires when the lease is released (cleanup hook). For queued
   *  waiters whose request was not granted at acquire time, this is
   *  the only signal that the device became free without them being
   *  awarded the lease (they may then choose to ``acquire()`` again
   *  themselves; wake-word uses this to re-arm). */
  onReleased?: () => void;
}

export interface Lease {
  /** Stable identifier (incrementing). Stale leases match a held lease
   *  by identity only — release() compares the active lease's id. */
  readonly id: number;
  readonly holder: string;
  readonly priority: number;
}

interface QueuedRequest extends AcquireOptions {
  /** Lease object that WILL be handed back to onAcquired when promoted.
   *  Distinct from the lease returned synchronously (queued requests
   *  return ``null`` synchronously per the API contract). */
  pendingLease: Lease;
}

let _nextLeaseId = 1;
let _activeLease: Lease | null = null;
let _activeOpts: AcquireOptions | null = null;
let _queue: QueuedRequest[] = [];

/** Acquire the SR singleton.
 *
 *  Returns a lease when granted; ``null`` when queued (the request is
 *  remembered and ``onAcquired`` will fire when promoted) OR when the
 *  current holder has equal-or-higher priority and the request must
 *  wait. Ties never preempt.
 *
 *  When a higher-priority request arrives while a lower-priority
 *  holder is active, the current holder's ``onPreempted`` fires and
 *  the new request is granted synchronously in the same tick. */
export function acquire(opts: AcquireOptions): Lease | null {
  // No current holder — grant immediately.
  if (_activeLease === null) {
    return _grantSync(opts);
  }
  // Higher priority — preempt the active holder.
  if (opts.priority > _activeLease.priority) {
    _preemptActive(opts.holder);
    return _grantSync(opts);
  }
  // Equal or lower — queue. Pre-allocate the lease id so we can hand
  // it to onAcquired when promoted; the synchronous return value is
  // null per the API contract (caller knows: null = wait).
  const pendingLease: Lease = {
    id: _nextLeaseId++,
    holder: opts.holder,
    priority: opts.priority,
  };
  _queue.push({ ...opts, pendingLease });
  return null;
}

/** Release a lease. Idempotent on stale leases (after preemption,
 *  release is a no-op). */
export function release(lease: Lease): void {
  if (_activeLease === null) return;
  if (_activeLease.id !== lease.id) return; // stale — preempted earlier.
  const releasedOpts = _activeOpts;
  _activeLease = null;
  _activeOpts = null;
  releasedOpts?.onReleased?.();
  // Notify queued waiters that the device freed (lets wake-word
  // re-arm via its own ``acquire`` call from ``onReleased``).
  // Snapshot the queue: any waiter's ``onReleased`` may call
  // ``acquire`` itself, which would re-enter and mutate _queue.
  const snapshot = _queue.slice();
  for (const q of snapshot) {
    q.onReleased?.();
  }
  // Promote the highest-priority queued waiter, if any survived the
  // snapshot phase (they may have self-promoted via a new acquire()).
  _promoteNext();
}

/** Read-only observer (HXI / tests). */
export function currentHolder(): { holder: string; priority: number } | null {
  if (_activeLease === null) return null;
  return { holder: _activeLease.holder, priority: _activeLease.priority };
}

/** Reset all state. Tests only. */
export function _resetForTests(): void {
  _activeLease = null;
  _activeOpts = null;
  _queue = [];
  _nextLeaseId = 1;
}

/** Internal: grant a fresh lease synchronously. */
function _grantSync(opts: AcquireOptions): Lease {
  const lease: Lease = {
    id: _nextLeaseId++,
    holder: opts.holder,
    priority: opts.priority,
  };
  _activeLease = lease;
  _activeOpts = opts;
  // Fire onAcquired AFTER state is committed so handlers see
  // currentHolder() returning the new holder.
  opts.onAcquired?.(lease);
  return lease;
}

/** Internal: invalidate the active holder. */
function _preemptActive(byHolder: string): void {
  const preempted = _activeOpts;
  _activeLease = null;
  _activeOpts = null;
  preempted?.onPreempted?.(byHolder);
}

/** Internal: dequeue and grant to the highest-priority queued waiter
 *  that still wants the lease. */
function _promoteNext(): void {
  if (_activeLease !== null) return;
  if (_queue.length === 0) return;
  // Pick highest priority; FIFO within the same priority.
  let bestIdx = 0;
  for (let i = 1; i < _queue.length; i++) {
    if (_queue[i].priority > _queue[bestIdx].priority) {
      bestIdx = i;
    }
  }
  const next = _queue.splice(bestIdx, 1)[0];
  _activeLease = next.pendingLease;
  _activeOpts = {
    holder: next.holder,
    priority: next.priority,
    onAcquired: next.onAcquired,
    onPreempted: next.onPreempted,
    onReleased: next.onReleased,
  };
  next.onAcquired?.(next.pendingLease);
}
