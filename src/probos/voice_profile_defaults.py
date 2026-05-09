"""AD-718: Default VoiceProfile values keyed on agent_type.

Captain picks `voice_name` per machine via the HXI; the values below seed only
pitch/rate so each crew member sounds distinct out of the box. Values are
deliberately conservative — small offsets from the global 0.9/0.95 defaults
to avoid uncanny variation when the user has only the basic OS voice set.
"""

from __future__ import annotations

import logging

from probos.crew_profile import VoiceProfile

logger = logging.getLogger(__name__)

# Keyed on agent_type (== crew_profiles/<agent_type>.yaml stem).
# Empty voice_name means "use global default voice and apply these pitch/rate".
DEFAULT_VOICE_PROFILES: dict[str, VoiceProfile] = {
    # bridge
    "counselor":            VoiceProfile(voice_name="", pitch=1.05, rate=0.92, volume=0.85),  # Troi — warm, slower
    # security
    "security_officer":     VoiceProfile(voice_name="", pitch=0.70, rate=0.95, volume=0.85),  # Worf — deep, firm
    # medical
    "diagnostician":        VoiceProfile(voice_name="", pitch=0.90, rate=1.05, volume=0.80),  # Bones — slightly clipped
    "pathologist":          VoiceProfile(voice_name="", pitch=1.00, rate=0.95, volume=0.80),  # Selar — precise, even
    "surgeon":              VoiceProfile(voice_name="", pitch=1.00, rate=1.00, volume=0.80),  # Pulaski
    "pharmacist":           VoiceProfile(voice_name="", pitch=1.05, rate=1.00, volume=0.80),  # Ogawa
    # science
    "architect":            VoiceProfile(voice_name="", pitch=0.95, rate=1.00, volume=0.80),  # Number One — measured
    "data_analyst":         VoiceProfile(voice_name="", pitch=1.00, rate=1.05, volume=0.80),  # Rahda
    "research_specialist":  VoiceProfile(voice_name="", pitch=1.00, rate=1.00, volume=0.80),  # Brahms
    "systems_analyst":      VoiceProfile(voice_name="", pitch=1.00, rate=1.00, volume=0.80),  # Dax
    "scout":                VoiceProfile(voice_name="", pitch=1.10, rate=1.05, volume=0.80),  # Wesley — younger
    # engineering
    "builder":              VoiceProfile(voice_name="", pitch=0.95, rate=1.05, volume=0.80),  # Forge
    "engineering_officer":  VoiceProfile(voice_name="", pitch=1.00, rate=1.00, volume=0.80),  # LaForge
    # operations
    "operations_officer":   VoiceProfile(voice_name="", pitch=0.90, rate=1.00, volume=0.80),  # O'Brien
    "training_officer":     VoiceProfile(voice_name="", pitch=1.00, rate=1.00, volume=0.80),  # Tucker
}


def default_voice_for(agent_type: str) -> VoiceProfile:
    """Return the seeded VoiceProfile for an agent_type, or a generic default."""
    if agent_type in DEFAULT_VOICE_PROFILES:
        return DEFAULT_VOICE_PROFILES[agent_type]
    return VoiceProfile()  # 0.9/0.95/0.8 — matches voice.ts v0 behaviour
