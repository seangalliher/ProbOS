# AD-718e — Multi-language voice selection

**Status:** Draft v1.
**Closes:** #526.
**Dependencies:** AD-718 (Wave 133 VoiceProfile). BF-291 / AD-738f (Wave 165 — `/api/avatars/tts/voices` enumeration). AD-738 (Wave 158 piper backend).
**Estimated tests:** +8 pytest + +5 vitest. **0 new pip/npm deps.**

---

## Problem

`VoiceProfile` in `src/probos/crew_profile.py:96` has no language/locale field. Voice resolution in `ui/src/audio/voice.ts:93` falls back to "any English voice" without honoring a per-agent language preference. The Piper voice catalog in `scripts/piper-voice-fetch.ps1` covers en_US and en_GB only.

## Solution

Add `language: str = "en"` field to `VoiceProfile`. Extend the piper voice catalog with es/fr/de/it/nl/pt rhasspy voices. UI voice picker filters by language. Server `/api/avatars/tts/voices` already returns parsed `lang` (BF-291) — no change there.

### Section 1 — `VoiceProfile.language` field

`src/probos/crew_profile.py` — add field after `wake_phrase`:

```python
language: str = "en"
"""AD-718e: ISO 639-1 language code (or BCP 47 short tag like 'en-US').
Used by the HXI voice picker to filter the available voice list, and
by browser SpeechSynthesis fallback resolution (prefer voices whose
``lang`` field starts with this prefix before falling back to en).
Empty string is normalized to 'en' for backward-compat."""
```

`__post_init__` validation:
- Strip whitespace.
- Empty string → "en" (backward-compat — existing rows without the field deserialize to "en").
- Length ≤ 16.
- Must match `^[a-z]{2,3}([_-][A-Za-z0-9]{2,8})?$` (basic BCP 47 shape).

`to_dict` / `from_dict` extend the tuple to include `"language"`.

Default-factory backward compat: existing on-disk profiles without `language` deserialize via `from_dict` which uses `.get()`-equivalent — verify behavior with a roundtrip test on a dict that omits `language`.

### Section 2 — Voice resolution in `voice.ts`

`ui/src/audio/voice.ts` — modify the voice-selection helper (around line 93):

Current behavior:
```ts
|| voices.find(v => v.lang.startsWith('en')) || null;
```

New behavior — when a `VoiceProfile.language` is present, prefer it before falling back to `en`:

```ts
const preferred = profile?.language || 'en';
return voices.find(v => v.name === profile?.voice_name)
    || voices.find(v => v.lang.startsWith(preferred))
    || voices.find(v => v.lang.startsWith('en'))
    || voices[0]
    || null;
```

Cast `profile?.language` from a new optional field on the TypeScript `VoiceProfile` type — find the interface declaration in `ui/src/types/` (verify with grep before edit) and add `language?: string`.

### Section 3 — `getServerPiperVoices` already returns `lang`

`ui/src/audio/voice.ts:368` — the function returns `PiperVoiceEntry[]` which (per BF-291 router parsing) already has `lang`/`voice`/`quality` split fields. No server-side change needed.

### Section 4 — UI voice picker `lang` filter

`ui/src/components/profile/ProfileInfoTab.tsx` (line 81: `getServerPiperVoices()` consumer) — add a language filter dropdown above the voice list. When the picker opens:

1. Read distinct `lang` values from the fetched voices.
2. Render a `<select>` with options: "All", then sorted distinct lang codes.
3. Default selected value: the current `VoiceProfile.language` for the agent (read from the profile context).
4. Filter the voice list reactively.

The voice picker's selection MUST set BOTH `voice_name` AND `language` on the profile — picking `es_ES-mls_*` updates `language` to `es` automatically. Document this contract in a code comment.

### Section 5 — Catalog expansion

`scripts/piper-voice-fetch.ps1` — append to the `$voices` array (after the en_GB block, before the closing `)`):

```powershell
# es_ES medium
@{ lang = "es"; region = "es_ES"; voice = "mls_9972";    quality = "medium" }
@{ lang = "es"; region = "es_ES"; voice = "carlfm";      quality = "medium" }
# es_MX low (only low ships)
@{ lang = "es"; region = "es_MX"; voice = "ald";         quality = "low"    }
# fr_FR medium
@{ lang = "fr"; region = "fr_FR"; voice = "siwis";       quality = "medium" }
@{ lang = "fr"; region = "fr_FR"; voice = "tom";         quality = "medium" }
@{ lang = "fr"; region = "fr_FR"; voice = "upmc";        quality = "medium" }
# fr_FR low
@{ lang = "fr"; region = "fr_FR"; voice = "mls_1840";    quality = "low"    }
# de_DE medium
@{ lang = "de"; region = "de_DE"; voice = "thorsten";    quality = "medium" }
@{ lang = "de"; region = "de_DE"; voice = "kerstin";     quality = "medium" }
@{ lang = "de"; region = "de_DE"; voice = "ramona";      quality = "low"    }
@{ lang = "de"; region = "de_DE"; voice = "eva_k";       quality = "medium" }
@{ lang = "de"; region = "de_DE"; voice = "karlsson";    quality = "medium" }
@{ lang = "de"; region = "de_DE"; voice = "pavoque";     quality = "low"    }
# it_IT medium
@{ lang = "it"; region = "it_IT"; voice = "riccardo";    quality = "medium" }
@{ lang = "it"; region = "it_IT"; voice = "paola";       quality = "medium" }
# nl_NL medium
@{ lang = "nl"; region = "nl_NL"; voice = "mls";         quality = "medium" }
@{ lang = "nl"; region = "nl_BE"; voice = "nathalie";    quality = "medium" }
# pt_BR medium
@{ lang = "pt"; region = "pt_BR"; voice = "edresson";    quality = "low"    }
@{ lang = "pt"; region = "pt_BR"; voice = "faber";       quality = "medium" }
```

Comment block above the catalog: "All entries sourced from huggingface.co/rhasspy/piper-voices (Apache 2.0 / MIT — verified 2026-05-16 on the rhasspy HF repo). Voice availability subject to upstream catalog stability; failed downloads honest-degrade in the script's per-voice try/catch."

**Pre-flight gate before this AD ships:** the Builder runs `./scripts/piper-voice-fetch.ps1` and confirms ≥90% of the new entries succeed. Any entry that 404s on HuggingFace is removed from the catalog and noted in the build report. The catalog is empirical, not normative.

### Tests

`tests/test_ad718e_voice_language.py` (+8):

1. `test_voice_profile_default_language_is_en`.
2. `test_voice_profile_language_normalized_empty_to_en` — `VoiceProfile(language="")` → `"en"`.
3. `test_voice_profile_language_strips_whitespace`.
4. `test_voice_profile_language_rejects_invalid_chars` — e.g. `"en/US"` raises.
5. `test_voice_profile_language_accepts_es_fr_de`.
6. `test_voice_profile_to_dict_includes_language`.
7. `test_voice_profile_from_dict_missing_language_defaults_to_en` — backward-compat.
8. `test_voice_profile_language_persists_through_crew_profile_roundtrip`.

`ui/src/__tests__/voice.test.ts` extend (+3):

9. `prefers_voice_matching_profile_language_over_en_fallback` — voices: [{lang:'en-US'}, {lang:'es-ES'}]; profile.language='es'; assert es-ES picked.
10. `falls_back_to_en_when_profile_language_voice_unavailable`.
11. `defaults_to_en_when_profile_language_undefined` — preserves AD-718 behavior.

`ui/src/__tests__/ProfileInfoTab.lang-filter.test.tsx` (+2):

12. `lang_filter_dropdown_renders_distinct_lang_codes_from_voices`.
13. `lang_filter_selection_filters_voice_list`.

## What This Does NOT Change

- Default `VoiceProfile()` behavior unchanged (defaults to `"en"`, picks any en voice — byte-identical to AD-718 behavior).
- Existing en_US / en_GB voices in the catalog unchanged.
- BF-291 `/api/avatars/tts/voices` endpoint unchanged (already returns `lang`).
- Piper voice resolution unchanged (operator-chosen `voice_model` is still authoritative; multi-language is for selection UX, not silent re-routing).
- AD-705b offline TTS / AD-723 Coqui backend out of scope.

## Tracking

- `PROGRESS.md` — Wave 166 entry.
- `docs/development/roadmap.md` — close #526.
- `DECISIONS.md` — append AD-718e. Note ISO 639-1 + BCP 47-short shape; rhasspy voice provenance.

Forward markers (TECHNICAL triggers):
- AD-718e-1 — Auto-detect language from agent's recent reply text (rule-based or fastText). Trigger: ≥3 operator requests for auto-routing.
- AD-718e-2 — Per-agent multi-voice composition (different voices for different intents). Trigger: AD-718a wake-phrase per-emotion lands.
- AD-718e-3 — Language-aware emotion modulation (some pitch/rate ranges don't translate). Trigger: voice complaints on non-en synthesis.

## Acceptance Criteria

- 8 pytest + 5 vitest green under serial + parallel gates.
- Full pytest gate: previous +N → ≥+8. Vitest: previous +N → ≥+5.
- `cd ui && npm run build` GREEN (AD-738b standing rule).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- ≥90% of new catalog entries successfully download via `./scripts/piper-voice-fetch.ps1` (pre-flight gate).
- No new pip/npm deps.

## Verified Against Codebase (2026-05-16)

```
grep -n "class VoiceProfile" src/probos/crew_profile.py
  96: class VoiceProfile:

grep -n "voice_name" src/probos/crew_profile.py
  105:     voice_name: str = ""    # SpeechSynthesisVoice.name; "" = use global default
  151:                 "voice_name", "pitch", "rate", "volume", "wake_phrase",

grep -n "wake_phrase" src/probos/crew_profile.py
  108:     # AD-718c: optional per-agent wake phrase. Empty string == no per-agent
  110:     # wake (system-wide "Computer" still routes to the agent via @callsign).

grep -n "getServerPiperVoices" ui/src/audio/voice.ts
  368: export async function getServerPiperVoices(): Promise<PiperVoiceEntry[] | null> {

grep -n "v.lang.startsWith" ui/src/audio/voice.ts
  93:   ) || voices.find(v => v.lang.startsWith('en')) || null;
  353:   return speechSynthesis.getVoices().filter(v => v.lang.startsWith('en'));

grep -n "getServerPiperVoices" ui/src/components/profile/ProfileInfoTab.tsx
  6:   getServerPiperVoices,
  81:       const piper = await getServerPiperVoices();

grep -n '@{ lang = "en"' scripts/piper-voice-fetch.ps1
  (catalog block starting line 22)
```

rhasspy/piper-voices HuggingFace repo confirmed Apache 2.0 / MIT (per user memory `/memories/probos-architect-learnings.md` license discipline + per `tools/piper` existing fetch).
