"""Tests for M365 connector agents."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from probos.integrations.m365_connector import (
    OutlookAgent, TeamsAgent, CalendarAgent, SharePointAgent, OneDriveAgent
)


@pytest.fixture
def mock_runtime():
    """Mock runtime."""
    return MagicMock()


@pytest.fixture
def mock_token_manager():
    """Mock M365TokenManager."""
    tm = MagicMock()
    tm.get_token = AsyncMock(return_value="test-token")
    return tm


class TestOutlookAgent:
    """Tests for OutlookAgent."""

    def test_outlook_agent_creation(self, mock_runtime, mock_token_manager):
        """Test creating OutlookAgent instance."""
        agent = OutlookAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        assert agent.agent_type == "outlook"
        assert agent.callsign == "Outlook"

    @pytest.mark.asyncio
    async def test_outlook_refresh_token_success(self, mock_runtime, mock_token_manager):
        """Test OutlookAgent refresh_token with valid token."""
        agent = OutlookAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        result = await agent.refresh_token()
        assert result is True

    @pytest.mark.asyncio
    async def test_outlook_refresh_token_failure(self, mock_runtime):
        """Test OutlookAgent refresh_token when token unavailable."""
        mock_tm = MagicMock()
        mock_tm.get_token = AsyncMock(return_value=None)
        agent = OutlookAgent(runtime=mock_runtime, token_manager=mock_tm)
        result = await agent.refresh_token()
        assert result is False

    @pytest.mark.asyncio
    async def test_outlook_list_changes(self, mock_runtime, mock_token_manager):
        """Test OutlookAgent list_changes."""
        agent = OutlookAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        changes = await agent.list_changes(datetime.now())
        assert isinstance(changes, list)

    @pytest.mark.asyncio
    async def test_outlook_get_audit_entry(self, mock_runtime, mock_token_manager):
        """Test OutlookAgent get_audit_entry."""
        agent = OutlookAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        entry = await agent.get_audit_entry("test-id")
        assert "resource_id" in entry
        assert entry["resource_id"] == "test-id"
        assert "action" in entry


class TestTeamsAgent:
    """Tests for TeamsAgent."""

    def test_teams_agent_creation(self, mock_runtime, mock_token_manager):
        """Test creating TeamsAgent instance."""
        agent = TeamsAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        assert agent.agent_type == "teams"
        assert agent.callsign == "Teams"

    @pytest.mark.asyncio
    async def test_teams_refresh_token_success(self, mock_runtime, mock_token_manager):
        """Test TeamsAgent refresh_token with valid token."""
        agent = TeamsAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        result = await agent.refresh_token()
        assert result is True

    @pytest.mark.asyncio
    async def test_teams_list_changes(self, mock_runtime, mock_token_manager):
        """Test TeamsAgent list_changes."""
        agent = TeamsAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        changes = await agent.list_changes(datetime.now())
        assert isinstance(changes, list)


class TestCalendarAgent:
    """Tests for CalendarAgent."""

    def test_calendar_agent_creation(self, mock_runtime, mock_token_manager):
        """Test creating CalendarAgent instance."""
        agent = CalendarAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        assert agent.agent_type == "calendar"
        assert agent.callsign == "Calendar"

    @pytest.mark.asyncio
    async def test_calendar_refresh_token_success(self, mock_runtime, mock_token_manager):
        """Test CalendarAgent refresh_token with valid token."""
        agent = CalendarAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        result = await agent.refresh_token()
        assert result is True

    @pytest.mark.asyncio
    async def test_calendar_list_changes(self, mock_runtime, mock_token_manager):
        """Test CalendarAgent list_changes."""
        agent = CalendarAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        changes = await agent.list_changes(datetime.now())
        assert isinstance(changes, list)


class TestSharePointAgent:
    """Tests for SharePointAgent."""

    def test_sharepoint_agent_creation(self, mock_runtime, mock_token_manager):
        """Test creating SharePointAgent instance."""
        agent = SharePointAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        assert agent.agent_type == "sharepoint"
        assert agent.callsign == "SharePoint"

    @pytest.mark.asyncio
    async def test_sharepoint_refresh_token_success(self, mock_runtime, mock_token_manager):
        """Test SharePointAgent refresh_token with valid token."""
        agent = SharePointAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        result = await agent.refresh_token()
        assert result is True

    @pytest.mark.asyncio
    async def test_sharepoint_list_changes(self, mock_runtime, mock_token_manager):
        """Test SharePointAgent list_changes."""
        agent = SharePointAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        changes = await agent.list_changes(datetime.now())
        assert isinstance(changes, list)


class TestOneDriveAgent:
    """Tests for OneDriveAgent."""

    def test_onedrive_agent_creation(self, mock_runtime, mock_token_manager):
        """Test creating OneDriveAgent instance."""
        agent = OneDriveAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        assert agent.agent_type == "onedrive"
        assert agent.callsign == "OneDrive"

    @pytest.mark.asyncio
    async def test_onedrive_refresh_token_success(self, mock_runtime, mock_token_manager):
        """Test OneDriveAgent refresh_token with valid token."""
        agent = OneDriveAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        result = await agent.refresh_token()
        assert result is True

    @pytest.mark.asyncio
    async def test_onedrive_list_changes(self, mock_runtime, mock_token_manager):
        """Test OneDriveAgent list_changes."""
        agent = OneDriveAgent(runtime=mock_runtime, token_manager=mock_token_manager)
        changes = await agent.list_changes(datetime.now())
        assert isinstance(changes, list)
