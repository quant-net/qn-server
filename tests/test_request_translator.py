"""
Unit tests for request_translator module, focusing on agent validation logic.
"""

import time
import pytest
from unittest.mock import Mock, MagicMock, patch
from collections import Counter

from quantnet_controller.common.request_translator import (
    _validate_agent_requirements,
    match_agent_to_exp,
)
from quantnet_controller.common.experimentdefinitions import Experiment, AgentSequences
from quantnet_controller.common.plugin import Path


# Mock classes for testing
class MockSequence:
    """Mock Sequence class for testing."""
    def __init__(self, name, duration_ms=100):
        self.name = name
        self.duration_ms = duration_ms


class MockAgentSequence:
    """Mock AgentSequence class for testing."""
    def __init__(self, name, node_type, sequences=None):
        self.name = name
        self.node_type = node_type
        self.sequences = sequences or [MockSequence(f"{name}_seq")]


class MockExperiment:
    """Mock Experiment class for testing."""
    def __init__(self, name, agent_sequences):
        self.name = name
        self.agent_sequences = agent_sequences


class MockSystemSettings:
    """Mock SystemSettings class for testing."""
    def __init__(self, node_id, node_type):
        self.ID = node_id
        self.type = node_type


class MockNode:
    """Mock Node class for testing."""
    def __init__(self, node_id, node_type, last_seen=None):
        self.systemSettings = MockSystemSettings(node_id, node_type)
        self.last_seen = last_seen


# Test fixtures
@pytest.fixture
def qnode_sequence():
    """Create a QNode agent sequence."""
    return MockAgentSequence("QNode_seq", "QNode")


@pytest.fixture
def mnode_sequence():
    """Create an MNode agent sequence."""
    return MockAgentSequence("MNode_seq", "MNode")


@pytest.fixture
def simple_experiment(qnode_sequence, mnode_sequence):
    """Create a simple experiment requiring QNode and MNode."""
    return MockExperiment("SimpleExp", [qnode_sequence, mnode_sequence])


@pytest.fixture
def dual_qnode_experiment(qnode_sequence):
    """Create an experiment requiring two QNodes."""
    return MockExperiment("DualQNodeExp", [qnode_sequence, qnode_sequence])


@pytest.fixture
def qnode_mnode_qnode_experiment(qnode_sequence, mnode_sequence):
    """Create an experiment requiring QNode, MNode, QNode."""
    return MockExperiment(
        "ComplexExp",
        [qnode_sequence, mnode_sequence, qnode_sequence]
    )


# Tests for _validate_agent_requirements()
class TestValidateAgentRequirements:
    """Test suite for _validate_agent_requirements function."""

    def test_all_agents_available(self, simple_experiment):
        """Test validation passes when all required agents are available."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now),
        ]
        
        is_valid, required_types, available_types, missing_types = (
            _validate_agent_requirements(simple_experiment, nodes)
        )
        
        assert is_valid is True
        assert required_types == ["QNode", "MNode"]
        assert available_types == ["QNode", "MNode"]
        assert missing_types == []

    def test_missing_agent_type(self, simple_experiment):
        """Test validation fails when required agent type is missing."""
        now = time.time()
        nodes = [MockNode("node_1", "QNode", last_seen=now)]
        
        with pytest.raises(ValueError) as exc_info:
            _validate_agent_requirements(simple_experiment, nodes)
        
        assert "Agent validation failed" in str(exc_info.value)
        assert "MNode" in str(exc_info.value)

    def test_insufficient_agent_count(self, dual_qnode_experiment):
        """Test validation fails when insufficient agents of required type."""
        now = time.time()
        nodes = [MockNode("node_1", "QNode", last_seen=now)]
        
        with pytest.raises(ValueError) as exc_info:
            _validate_agent_requirements(dual_qnode_experiment, nodes)
        
        assert "Agent validation failed" in str(exc_info.value)
        assert "QNode" in str(exc_info.value)

    def test_extra_agents_ok(self, simple_experiment):
        """Test validation passes with extra agents beyond requirements."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now),
            MockNode("node_3", "QNode", last_seen=now),  # Extra QNode
        ]
        
        is_valid, required_types, available_types, missing_types = (
            _validate_agent_requirements(simple_experiment, nodes)
        )
        
        assert is_valid is True
        assert missing_types == []

    def test_complex_agent_requirements(self, qnode_mnode_qnode_experiment):
        """Test validation with complex requirements (QNode, MNode, QNode)."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now),
            MockNode("node_3", "QNode", last_seen=now),
        ]
        
        is_valid, required_types, available_types, missing_types = (
            _validate_agent_requirements(qnode_mnode_qnode_experiment, nodes)
        )
        
        assert is_valid is True
        assert required_types == ["QNode", "MNode", "QNode"]
        assert missing_types == []

    def test_empty_path(self, simple_experiment):
        """Test validation fails with empty path."""
        nodes = []
        
        with pytest.raises(ValueError) as exc_info:
            _validate_agent_requirements(simple_experiment, nodes)
        
        assert "Agent validation failed" in str(exc_info.value)

    def test_empty_experiment(self):
        """Test validation passes with empty experiment requirements."""
        exp = MockExperiment("EmptyExp", [])
        now = time.time()
        nodes = [MockNode("node_1", "QNode", last_seen=now)]
        
        is_valid, required_types, available_types, missing_types = (
            _validate_agent_requirements(exp, nodes)
        )
        
        assert is_valid is True
        assert required_types == []
        assert missing_types == []

    def test_string_node_ids(self, simple_experiment):
        """Test validation with string node IDs instead of node objects."""
        nodes = ["QNode", "MNode"]
        
        is_valid, required_types, available_types, missing_types = (
            _validate_agent_requirements(simple_experiment, nodes)
        )
        
        assert is_valid is True
        assert available_types == ["QNode", "MNode"]

    def test_mixed_node_types(self, simple_experiment):
        """Test validation with mixed node objects and string IDs."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            "MNode",
        ]
        
        is_valid, required_types, available_types, missing_types = (
            _validate_agent_requirements(simple_experiment, nodes)
        )
        
        assert is_valid is True
        assert available_types == ["QNode", "MNode"]

    def test_error_message_contains_details(self, dual_qnode_experiment):
        """Test that error message contains detailed information about missing agents."""
        now = time.time()
        nodes = [MockNode("node_1", "QNode", last_seen=now)]
        
        with pytest.raises(ValueError) as exc_info:
            _validate_agent_requirements(dual_qnode_experiment, nodes)
        
        error_msg = str(exc_info.value)
        assert "required" in error_msg.lower()
        assert "available" in error_msg.lower()


# Tests for match_agent_to_exp()
class TestMatchAgentToExp:
    """Test suite for match_agent_to_exp function."""

    def test_successful_match_with_validation(self, simple_experiment):
        """Test successful agent matching with validation enabled."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now),
        ]
        path = Mock()
        path.hops = nodes
        
        result = match_agent_to_exp(simple_experiment, path, validate=True)
        
        assert result == ["node_1", "node_2"]

    def test_validation_failure_raises_exception(self, simple_experiment):
        """Test that validation failure raises ValueError."""
        now = time.time()
        nodes = [MockNode("node_1", "QNode", last_seen=now)]
        path = Mock()
        path.hops = nodes
        
        with pytest.raises(ValueError):
            match_agent_to_exp(simple_experiment, path, validate=True)

    def test_backward_compatibility_validate_false(self, simple_experiment):
        """Test backward compatibility with validate=False."""
        now = time.time()
        nodes = [MockNode("node_1", "QNode", last_seen=now)]
        path = Mock()
        path.hops = nodes
        
        # Should not raise exception even though MNode is missing
        result = match_agent_to_exp(simple_experiment, path, validate=False)
        
        # Should return partial mapping
        assert "node_1" in result

    def test_non_mutating_behavior(self, simple_experiment):
        """Test that match_agent_to_exp doesn't mutate the original nodes list."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now),
        ]
        original_length = len(nodes)
        path = Mock()
        path.hops = nodes
        
        match_agent_to_exp(simple_experiment, path, validate=True)
        
        # Original list should not be modified
        assert len(nodes) == original_length

    def test_order_preservation(self, qnode_mnode_qnode_experiment):
        """Test that agents are matched in the order required by experiment."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now),
            MockNode("node_3", "QNode", last_seen=now),
        ]
        path = Mock()
        path.hops = nodes
        
        result = match_agent_to_exp(qnode_mnode_qnode_experiment, path, validate=True)
        
        # Should match in order: QNode, MNode, QNode
        assert result == ["node_1", "node_2", "node_3"]

    def test_optical_switch_filtered(self, simple_experiment):
        """Test that OpticalSwitch nodes are filtered out."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("switch_1", "OpticalSwitch", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now),
        ]
        path = Mock()
        path.hops = nodes
        
        result = match_agent_to_exp(simple_experiment, path, validate=True)
        
        assert result == ["node_1", "node_2"]
        assert "switch_1" not in result

    def test_path_as_list(self, simple_experiment):
        """Test match_agent_to_exp with path as list instead of Path object."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now),
        ]
        
        result = match_agent_to_exp(simple_experiment, nodes, validate=True)
        
        assert result == ["node_1", "node_2"]

    def test_path_as_string_list(self, simple_experiment):
        """Test match_agent_to_exp with path as list of string IDs."""
        nodes = ["QNode", "MNode"]
        
        result = match_agent_to_exp(simple_experiment, nodes, validate=True)
        
        assert result == ["QNode", "MNode"]

    def test_none_path(self, simple_experiment):
        """Test match_agent_to_exp with None path."""
        path = Mock()
        path.hops = None
        
        with pytest.raises(ValueError):
            match_agent_to_exp(simple_experiment, path, validate=True)

    def test_default_validate_true(self, simple_experiment):
        """Test that validate=True is the default behavior."""
        now = time.time()
        nodes = [MockNode("node_1", "QNode", last_seen=now)]
        path = Mock()
        path.hops = nodes
        
        # Should raise ValueError because MNode is missing
        with pytest.raises(ValueError):
            match_agent_to_exp(simple_experiment, path)  # validate defaults to True


# Integration tests
class TestIntegration:
    """Integration tests for validation workflow."""

    def test_validation_workflow_success(self, simple_experiment):
        """Test complete validation workflow with valid path."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now),
        ]
        path = Mock()
        path.hops = nodes
        
        # Should not raise exception
        result = match_agent_to_exp(simple_experiment, path, validate=True)
        
        assert len(result) == 2
        assert result[0] == "node_1"
        assert result[1] == "node_2"

    def test_validation_workflow_failure(self, simple_experiment):
        """Test complete validation workflow with invalid path."""
        now = time.time()
        nodes = [MockNode("node_1", "QNode", last_seen=now)]
        path = Mock()
        path.hops = nodes
        
        # Should raise ValueError with details
        with pytest.raises(ValueError) as exc_info:
            match_agent_to_exp(simple_experiment, path, validate=True)
        
        error_msg = str(exc_info.value)
        assert "MNode" in error_msg
        assert "required" in error_msg.lower()

    def test_multiple_missing_agents(self):
        """Test validation with multiple missing agent types."""
        now = time.time()
        exp = MockExperiment(
            "MultiExp",
            [
                MockAgentSequence("QNode_seq", "QNode"),
                MockAgentSequence("MNode_seq", "MNode"),
                MockAgentSequence("BSM_seq", "BSMNode"),
            ]
        )
        nodes = [MockNode("node_1", "QNode", last_seen=now)]
        path = Mock()
        path.hops = nodes
        
        with pytest.raises(ValueError) as exc_info:
            match_agent_to_exp(exp, path, validate=True)
        
        error_msg = str(exc_info.value)
        assert "MNode" in error_msg
        assert "BSMNode" in error_msg

    def test_count_mismatch_error_details(self, dual_qnode_experiment):
        """Test that count mismatch error includes required and available counts."""
        now = time.time()
        nodes = [MockNode("node_1", "QNode", last_seen=now)]
        path = Mock()
        path.hops = nodes
        
        with pytest.raises(ValueError) as exc_info:
            match_agent_to_exp(dual_qnode_experiment, path, validate=True)
        
        error_msg = str(exc_info.value)
        # Should indicate need for 2 QNodes but only 1 available
        assert "2" in error_msg or "required" in error_msg.lower()


# Edge case tests
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_large_path(self, simple_experiment):
        """Test validation with very large path."""
        now = time.time()
        nodes = [
            MockNode(f"node_{i}", "QNode" if i % 2 == 0 else "MNode", last_seen=now)
            for i in range(1000)
        ]
        path = Mock()
        path.hops = nodes
        
        result = match_agent_to_exp(simple_experiment, path, validate=True)
        
        assert len(result) == 2

    def test_duplicate_agent_types_in_sequence(self):
        """Test experiment with many duplicate agent types."""
        now = time.time()
        exp = MockExperiment(
            "ManyQNodes",
            [MockAgentSequence(f"QNode_{i}", "QNode") for i in range(10)]
        )
        nodes = [MockNode(f"node_{i}", "QNode", last_seen=now) for i in range(10)]
        path = Mock()
        path.hops = nodes
        
        result = match_agent_to_exp(exp, path, validate=True)
        
        assert len(result) == 10

    def test_case_sensitive_node_types(self, simple_experiment):
        """Test that node type matching is case-sensitive."""
        now = time.time()
        nodes = [
            MockNode("node_1", "qnode", last_seen=now),  # lowercase
            MockNode("node_2", "MNode", last_seen=now),
        ]
        path = Mock()
        path.hops = nodes
        
        # Should fail because "qnode" != "QNode"
        with pytest.raises(ValueError):
            match_agent_to_exp(simple_experiment, path, validate=True)

    def test_whitespace_in_node_types(self):
        """Test handling of whitespace in node types."""
        now = time.time()
        exp = MockExperiment(
            "WhitespaceExp",
            [MockAgentSequence("QNode_seq", "QNode ")]  # trailing space
        )
        nodes = [MockNode("node_1", "QNode", last_seen=now)]
        path = Mock()
        path.hops = nodes
        
        # Should fail because "QNode " != "QNode"
        with pytest.raises(ValueError):
            match_agent_to_exp(exp, path, validate=True)


# Tests for heartbeat timeout / last_seen validation
class TestHeartbeatTimeout:
    """Test suite for last_seen heartbeat timeout filtering in _validate_agent_requirements."""

    def test_recent_heartbeat_passes(self, simple_experiment):
        """Test that nodes with recent last_seen pass validation."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now),
        ]

        is_valid, _, available_types, _ = _validate_agent_requirements(
            simple_experiment, nodes
        )

        assert is_valid is True
        assert "QNode" in available_types
        assert "MNode" in available_types

    def test_stale_heartbeat_excluded(self, simple_experiment):
        """Test that nodes with stale last_seen are excluded."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now - 120),  # 2 minutes ago
        ]

        with pytest.raises(ValueError) as exc_info:
            _validate_agent_requirements(simple_experiment, nodes)

        error_msg = str(exc_info.value)
        assert "MNode" in error_msg
        assert "stale" in error_msg.lower()

    def test_no_last_seen_treated_as_stale(self, simple_experiment):
        """Test that nodes without last_seen attribute are treated as stale."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode"),  # no last_seen
        ]

        with pytest.raises(ValueError) as exc_info:
            _validate_agent_requirements(simple_experiment, nodes)

        assert "Agent validation failed" in str(exc_info.value)

    def test_custom_heartbeat_timeout(self, simple_experiment):
        """Test validation with a custom heartbeat timeout."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now - 30),  # 30s ago
            MockNode("node_2", "MNode", last_seen=now - 30),
        ]

        # With 60s timeout, should pass
        is_valid, _, _, _ = _validate_agent_requirements(
            simple_experiment, nodes, heartbeat_timeout=60
        )
        assert is_valid is True

        # With strict 10s timeout, should fail
        with pytest.raises(ValueError):
            _validate_agent_requirements(
                simple_experiment, nodes, heartbeat_timeout=10
            )

    def test_all_nodes_stale_fails(self, simple_experiment):
        """Test that validation fails when all nodes are stale."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now - 300),  # 5 min ago
            MockNode("node_2", "MNode", last_seen=now - 300),
        ]

        with pytest.raises(ValueError) as exc_info:
            _validate_agent_requirements(simple_experiment, nodes)

        assert "Agent validation failed" in str(exc_info.value)

    def test_string_nodes_bypass_heartbeat_check(self, simple_experiment):
        """Test that string node IDs bypass the heartbeat check."""
        nodes = ["QNode", "MNode"]

        is_valid, _, _, _ = _validate_agent_requirements(simple_experiment, nodes)
        assert is_valid is True

    def test_stale_error_includes_node_ids(self, simple_experiment):
        """Test that the error message includes stale node IDs."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("stale_mnode", "MNode", last_seen=now - 300),
        ]

        with pytest.raises(ValueError) as exc_info:
            _validate_agent_requirements(simple_experiment, nodes)

        error_msg = str(exc_info.value)
        assert "stale_mnode" in error_msg

    def test_boundary_exactly_at_timeout(self, simple_experiment):
        """Test node just past the timeout boundary is excluded."""
        now = time.time()
        nodes = [
            MockNode("node_1", "QNode", last_seen=now),
            MockNode("node_2", "MNode", last_seen=now - 60.001),  # just over 60s
        ]

        with pytest.raises(ValueError):
            _validate_agent_requirements(
                simple_experiment, nodes, heartbeat_timeout=60
            )

    def test_mixed_stale_and_fresh_same_type(self):
        """Test that stale nodes of a type don't block fresh ones of the same type."""
        exp = MockExperiment(
            "SingleQNode",
            [MockAgentSequence("QNode_seq", "QNode")]
        )
        now = time.time()
        nodes = [
            MockNode("stale_q", "QNode", last_seen=now - 300),
            MockNode("fresh_q", "QNode", last_seen=now),
        ]

        is_valid, _, available_types, _ = _validate_agent_requirements(exp, nodes)
        assert is_valid is True
        assert available_types == ["QNode"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
