/** BF-812: policy-denial recognition. */
import { describe, expect, it } from 'vitest';

import { denialNotice, policyDenialOf } from '../policyDenial';

describe('BF-812 policyDenialOf', () => {
  it('recognises the backend refusal shape', () => {
    expect(policyDenialOf({ error: 'intent_denied', reason: 'rbac' }))
      .toEqual({ reason: 'rbac' });
  });

  it('defaults the reason when the body omits it', () => {
    expect(policyDenialOf({ error: 'intent_denied' })).toEqual({ reason: 'policy' });
    expect(policyDenialOf({ error: 'intent_denied', reason: '' })).toEqual({ reason: 'policy' });
    expect(policyDenialOf({ error: 'intent_denied', reason: 42 })).toEqual({ reason: 'policy' });
  });

  it('is not fooled by an ordinary reply or a transport failure body', () => {
    // A denial must be distinguishable from every non-denial, or the Ward
    // Room fallback either reroutes a refusal or strands a real outage.
    expect(policyDenialOf({ response: 'here you go' })).toBeNull();
    expect(policyDenialOf({ error: 'internal_error' })).toBeNull();
    expect(policyDenialOf({ detail: 'Not Found' })).toBeNull();
    expect(policyDenialOf({})).toBeNull();
  });

  it('degrades on a non-object body rather than throwing', () => {
    // `res.json()` on an HTML error page yields a string or throws upstream;
    // neither may be mistaken for a refusal.
    for (const body of [null, undefined, 'intent_denied', 0, [], true]) {
      expect(policyDenialOf(body)).toBeNull();
    }
  });

  it('names the refusal without dressing it as an agent turn or an outage', () => {
    const text = denialNotice({ reason: 'rbac' });

    expect(text).toContain('rbac');
    expect(text.toLowerCase()).toContain('policy');
    // The defect this replaces rendered "(no response)", which reads as the
    // agent having nothing to say.
    expect(text.toLowerCase()).not.toContain('no response');
  });
});
