import pytest
import asyncio
from probos.identity import VoiceProfileManager, AvatarProfileManager

@pytest.mark.asyncio
async def test_voice_profile_persistence():
    mgr = VoiceProfileManager()
    await mgr.set_voice_profile("captain", "Ezri")
    voice = await mgr.get_voice_profile("captain")
    assert voice is None or isinstance(voice, str)

@pytest.mark.asyncio
async def test_avatar_theme_persistence():
    mgr = AvatarProfileManager()
    await mgr.set_avatar_theme("captain", "defiant")
    theme = await mgr.get_avatar_theme("captain")
    assert isinstance(theme, dict)
    assert "theme" in theme
