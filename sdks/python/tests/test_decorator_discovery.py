import os
from unittest.mock import patch
import pytest
from agent_control.control_decorators import control, DISCOVERED_POLICIES

class TestDecoratorDiscovery:
    """Tests for @control decorator policy discovery mechanism."""

    def setup_method(self):
        """Clear discovered policies before each test."""
        DISCOVERED_POLICIES.clear()

    def teardown_method(self):
        """Clear discovered policies after each test."""
        DISCOVERED_POLICIES.clear()

    def test_discovers_policy_name(self):
        """Test that policy name is added to registry at definition time."""
        
        @control(policy="discovered-policy-1")
        def my_func():
            pass

        assert "discovered-policy-1" in DISCOVERED_POLICIES

    def test_identifies_location(self):
        """Test that decorator identifies and logs the correct location."""
        
        with patch("agent_control.control_decorators.logger") as mock_logger:
            # We define the function here to capture the line number
            # Line X
            @control(policy="location-test-policy")  # Line X+1
            def my_func():
                pass
            
            # Verify logger was called
            assert mock_logger.info.called
            
            # Extract the log message
            log_message = mock_logger.info.call_args[0][0]
            
            # Verify content
            assert "Found @control(policy='location-test-policy')" in log_message
            
            # Verify filename is this file
            current_file = os.path.basename(__file__)
            assert current_file in log_message
            
            # Verify it contains a line number (format is filename:lineno)
            # We don't assert exact line number to avoid brittleness, but check format
            assert ":" in log_message.split(" ")[-1]

    def test_handles_multiple_policies(self):
        """Test discovery of multiple different policies."""
        
        @control(policy="policy-a")
        def func_a(): pass
        
        @control(policy="policy-b")
        def func_b(): pass
        
        assert "policy-a" in DISCOVERED_POLICIES
        assert "policy-b" in DISCOVERED_POLICIES
        assert len(DISCOVERED_POLICIES) == 2

    def test_ignores_none_policy(self):
        """Test that decorators without policy arg don't register anything."""
        
        @control()
        def func_no_policy(): pass
        
        assert len(DISCOVERED_POLICIES) == 0

