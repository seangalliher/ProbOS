/* BF-937 (#1678): the Approve control of a build in review asks the vessel to merge it. Since BF-897 the vessel never
 * merges a build locally (a build is delivered through GitHub, AD-1336), so what the Captain needs from the click is the
 * vessel's answer, in the vessel's words: not merged, and where the candidate branch is kept. */

export const QUEUE_APPROVE_URL = '/api/build/queue/approve';

/** Shown when the vessel gave no readable answer: the click is not lost, and nothing is claimed about the build. */
export const QUEUE_APPROVE_NO_ANSWER = 'Approve request failed: no answer from the vessel. Nothing was merged.';

/** The line to show for the vessel's answer body: its `message`, or the fixed no-answer line when it sent none. */
export function queueApproveMessage(body: unknown): string {
  if (typeof body === 'object' && body !== null) {
    const message = (body as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim() !== '') return message;
  }
  return QUEUE_APPROVE_NO_ANSWER;
}

/** Ask the vessel to approve the build in review `buildId`; resolves to the line to show the Captain, and never rejects. */
export async function approveQueuedBuild(buildId: string): Promise<string> {
  try {
    const response = await fetch(QUEUE_APPROVE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ build_id: buildId }),
    });
    return queueApproveMessage(await response.json());
  } catch {
    return QUEUE_APPROVE_NO_ANSWER;
  }
}
