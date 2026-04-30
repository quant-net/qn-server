"""
Unit tests for changes introduced in fix_experiment_parameter_handling:
  - ExperimentType enum in constants.py
  - Experiment.type default in experimentdefinitions.py
  - translate_request: Parameter object conversion, exp_params default,
    getResult ordering, agent-ID error messages
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone

from quantnet_mq import Code
from quantnet_mq.schema.models import Parameter

from quantnet_controller.common.constants import ExperimentType
from quantnet_controller.common.experimentdefinitions import Experiment, AgentSequences
from quantnet_controller.common.request_translator import RequestTranslator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_translator(request_type=None):
    """Return a RequestTranslator instance without triggering __init__ I/O."""
    translator = object.__new__(RequestTranslator)
    translator.context = MagicMock()
    translator.exp_defs = []
    translator.lock = asyncio.Lock()
    translator.request_type = request_type or MagicMock(__name__="experiment")
    return translator


def ok_result(agent_id="agent-1"):
    return {"status": {"code": Code.OK.value}, "agentId": agent_id}


def queued_result(agent_id="agent-1"):
    return {"status": {"code": Code.QUEUED.value}, "agentId": agent_id}


def failed_result():
    return {"status": {"code": Code.FAILED.value}}


class MockSequence:
    def __init__(self, name, duration_ms=100, class_name="Seq"):
        self.name = name
        self.class_name = class_name
        from datetime import timedelta
        self.duration = timedelta(milliseconds=duration_ms)
        self.dependency = None


class MockAgentSequence:
    def __init__(self, name, node_type="QNode"):
        self.name = name
        self.node_type = node_type
        self.sequences = [MockSequence(f"{name}_seq")]


class MockExp:
    def __init__(self, agent_ids):
        self.name = "TestExp"
        self.agent_sequences = [MockAgentSequence(f"seq_{a}") for a in agent_ids]


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# ExperimentType enum
# ---------------------------------------------------------------------------

class TestExperimentType:
    def test_calibration_value_and_label(self):
        assert ExperimentType.CALIBRATION == 1
        assert ExperimentType.CALIBRATION.label == "Calibration"

    def test_experiment_value_and_label(self):
        assert ExperimentType.EXPERIMENT == 2
        assert ExperimentType.EXPERIMENT.label == "Experiment"

    def test_test_value_and_label(self):
        assert ExperimentType.TEST == 3
        assert ExperimentType.TEST.label == "Test"

    def test_is_int_comparable(self):
        assert ExperimentType.CALIBRATION < ExperimentType.EXPERIMENT
        assert ExperimentType.EXPERIMENT < ExperimentType.TEST

    def test_three_members_only(self):
        assert len(ExperimentType) == 3


# ---------------------------------------------------------------------------
# Experiment.type default
# ---------------------------------------------------------------------------

class ConcreteExp(Experiment):
    name = "Concrete"
    agent_sequences = []

    def get_sequence(self, agent_index):
        return None


class CalibrationExp(Experiment):
    name = "Calibration"
    type = ExperimentType.CALIBRATION
    agent_sequences = []

    def get_sequence(self, agent_index):
        return None


class TestExperimentTypeAttribute:
    def test_default_type_is_experiment(self):
        assert ConcreteExp.type == ExperimentType.EXPERIMENT

    def test_instance_default_type(self):
        exp = ConcreteExp()
        assert exp.type == ExperimentType.EXPERIMENT

    def test_subclass_can_override_type(self):
        assert CalibrationExp.type == ExperimentType.CALIBRATION


# ---------------------------------------------------------------------------
# translate_request: Parameter conversion
# ---------------------------------------------------------------------------

class TestTranslateRequestParameterConversion:

    def _make_translator_with_mocks(self, agent_ids, submit_results, get_results):
        translator = make_translator()
        exp = MockExp(agent_ids)
        start_time = datetime.now(timezone.utc).timestamp()
        slots = {aid: MagicMock() for aid in agent_ids}
        for s in slots.values():
            s.__getitem__ = MagicMock(side_effect=lambda sl: MagicMock())
            s.__len__ = MagicMock(return_value=100)

        translator.get_slots_to_allocate = AsyncMock(return_value=(start_time, slots))
        translator.submit = AsyncMock(side_effect=submit_results)
        translator.getResult = AsyncMock(side_effect=get_results)
        return translator, exp

    def test_exp_params_dict_converted_to_parameter_objects(self):
        agent_ids = ["agent-1"]
        translator, exp = self._make_translator_with_mocks(
            agent_ids,
            submit_results=[ok_result("agent-1")],
            get_results=[ok_result("agent-1")],
        )

        exp_params = {"alpha": 0.5, "shots": 100}
        run(translator.translate_request("exp-1", exp, exp_params, agent_ids))

        # Verify submit was called with Parameter objects
        submitted_allocations = translator.submit.call_args[0][1]["allocations"]
        params_passed = submitted_allocations[0]["parameters"]
        assert all(isinstance(p, Parameter) for p in params_passed)
        names = {p.name for p in params_passed}
        values = {p.name: p.value for p in params_passed}
        assert names == {"alpha", "shots"}
        assert values["alpha"] == 0.5
        assert values["shots"] == 100

    def test_empty_exp_params_dict_does_not_crash(self):
        agent_ids = ["agent-1"]
        translator, exp = self._make_translator_with_mocks(
            agent_ids,
            submit_results=[ok_result("agent-1")],
            get_results=[ok_result("agent-1")],
        )

        result = run(translator.translate_request("exp-1", exp, {}, agent_ids))
        assert result == Code.OK

    def test_empty_exp_params_produces_empty_parameter_list(self):
        agent_ids = ["agent-1"]
        translator, exp = self._make_translator_with_mocks(
            agent_ids,
            submit_results=[ok_result("agent-1")],
            get_results=[ok_result("agent-1")],
        )

        run(translator.translate_request("exp-1", exp, {}, agent_ids))

        submitted_allocations = translator.submit.call_args[0][1]["allocations"]
        assert submitted_allocations[0]["parameters"] == []


# ---------------------------------------------------------------------------
# translate_request: getResult ordering
# ---------------------------------------------------------------------------

class TestTranslateRequestGetResultOrdering:

    def test_get_result_not_called_when_submit_fails(self):
        agent_ids = ["agent-1", "agent-2"]
        translator = make_translator()
        exp = MockExp(agent_ids)
        start_time = datetime.now(timezone.utc).timestamp()
        slots = {aid: MagicMock() for aid in agent_ids}
        translator.get_slots_to_allocate = AsyncMock(return_value=(start_time, slots))

        # First submit succeeds, second fails
        translator.submit = AsyncMock(side_effect=[ok_result("agent-1"), failed_result()])
        translator.getResult = AsyncMock()

        result = run(translator.translate_request("exp-1", exp, {}, agent_ids))

        assert result == Code.FAILED
        translator.getResult.assert_not_called()

    def test_get_result_not_called_when_submit_raises_exception(self):
        agent_ids = ["agent-1"]
        translator = make_translator()
        exp = MockExp(agent_ids)
        start_time = datetime.now(timezone.utc).timestamp()
        slots = {aid: MagicMock() for aid in agent_ids}
        translator.get_slots_to_allocate = AsyncMock(return_value=(start_time, slots))

        translator.submit = AsyncMock(side_effect=RuntimeError("connection refused"))
        translator.getResult = AsyncMock()

        result = run(translator.translate_request("exp-1", exp, {}, agent_ids))

        assert result == Code.FAILED
        translator.getResult.assert_not_called()

    def test_get_result_called_after_all_submits_succeed(self):
        agent_ids = ["agent-1", "agent-2"]
        translator = make_translator()
        exp = MockExp(agent_ids)
        start_time = datetime.now(timezone.utc).timestamp()
        slots = {aid: MagicMock() for aid in agent_ids}
        translator.get_slots_to_allocate = AsyncMock(return_value=(start_time, slots))
        translator.submit = AsyncMock(side_effect=[ok_result("agent-1"), ok_result("agent-2")])
        translator.getResult = AsyncMock(side_effect=[ok_result("agent-1"), ok_result("agent-2")])

        result = run(translator.translate_request("exp-1", exp, {}, agent_ids))

        assert result == Code.OK
        assert translator.getResult.call_count == 2


# ---------------------------------------------------------------------------
# translate_request: error messages include agent ID
# ---------------------------------------------------------------------------

class TestTranslateRequestErrorMessages:

    def _setup(self, agent_ids, submit_results, get_results=None):
        translator = make_translator()
        exp = MockExp(agent_ids)
        start_time = datetime.now(timezone.utc).timestamp()
        slots = {aid: MagicMock() for aid in agent_ids}
        translator.get_slots_to_allocate = AsyncMock(return_value=(start_time, slots))
        translator.submit = AsyncMock(side_effect=submit_results)
        if get_results is not None:
            translator.getResult = AsyncMock(side_effect=get_results)
        return translator, exp

    def test_submit_exception_message_includes_agent_id(self):
        agent_ids = ["agent-42"]
        translator, exp = self._setup(
            agent_ids,
            submit_results=[RuntimeError("timeout")],
        )
        handle = MagicMock()
        run(translator.translate_request("exp-1", exp, {}, agent_ids, handle_result=handle))

        error_msg = handle.call_args[0][1]
        assert "agent-42" in error_msg

    def test_submit_failed_status_message_includes_agent_id_and_code(self):
        agent_ids = ["agent-99"]
        translator, exp = self._setup(
            agent_ids,
            submit_results=[{"status": {"code": Code.FAILED.value}}],
        )
        handle = MagicMock()
        run(translator.translate_request("exp-1", exp, {}, agent_ids, handle_result=handle))

        error_msg = handle.call_args[0][1]
        assert "agent-99" in error_msg
        assert str(Code.FAILED.value) in error_msg

    def test_get_result_exception_message_includes_agent_id(self):
        agent_ids = ["agent-77"]
        translator, exp = self._setup(
            agent_ids,
            submit_results=[ok_result("agent-77")],
            get_results=[RuntimeError("timeout")],
        )
        handle = MagicMock()
        run(translator.translate_request("exp-1", exp, {}, agent_ids, handle_result=handle))

        error_msg = handle.call_args[0][1]
        assert "agent-77" in error_msg

    def test_get_result_bad_status_message_includes_agent_id(self):
        agent_ids = ["agent-55"]
        bad_result = {"status": {"code": Code.FAILED.value}, "agentId": "agent-55"}
        translator, exp = self._setup(
            agent_ids,
            submit_results=[ok_result("agent-55")],
            get_results=[bad_result],
        )
        handle = MagicMock()
        run(translator.translate_request("exp-1", exp, {}, agent_ids, handle_result=handle))

        error_msg = handle.call_args[0][1]
        assert "agent-55" in error_msg

    def test_multiple_agents_identifies_failing_agent(self):
        agent_ids = ["agent-A", "agent-B", "agent-C"]
        translator, exp = self._setup(
            agent_ids,
            submit_results=[
                ok_result("agent-A"),
                {"status": {"code": Code.FAILED.value}},
                ok_result("agent-C"),
            ],
        )
        handle = MagicMock()
        run(translator.translate_request("exp-1", exp, {}, agent_ids, handle_result=handle))

        error_msg = handle.call_args[0][1]
        assert "agent-B" in error_msg
        assert "agent-A" not in error_msg
        assert "agent-C" not in error_msg


# ---------------------------------------------------------------------------
# translate_request: successful path
# ---------------------------------------------------------------------------

class TestTranslateRequestSuccess:

    def test_returns_ok_on_success(self):
        agent_ids = ["agent-1"]
        translator = make_translator()
        exp = MockExp(agent_ids)
        start_time = datetime.now(timezone.utc).timestamp()
        slots = {aid: MagicMock() for aid in agent_ids}
        translator.get_slots_to_allocate = AsyncMock(return_value=(start_time, slots))
        translator.submit = AsyncMock(return_value=ok_result("agent-1"))
        translator.getResult = AsyncMock(return_value=ok_result("agent-1"))

        result = run(translator.translate_request("exp-1", exp, {}, agent_ids))
        assert result == Code.OK

    def test_queued_result_is_accepted(self):
        agent_ids = ["agent-1"]
        translator = make_translator()
        exp = MockExp(agent_ids)
        start_time = datetime.now(timezone.utc).timestamp()
        slots = {aid: MagicMock() for aid in agent_ids}
        translator.get_slots_to_allocate = AsyncMock(return_value=(start_time, slots))
        translator.submit = AsyncMock(return_value=ok_result("agent-1"))
        translator.getResult = AsyncMock(return_value=queued_result("agent-1"))

        result = run(translator.translate_request("exp-1", exp, {}, agent_ids))
        assert result == Code.OK

    def test_handle_result_called_per_agent(self):
        agent_ids = ["agent-1", "agent-2"]
        translator = make_translator()
        exp = MockExp(agent_ids)
        start_time = datetime.now(timezone.utc).timestamp()
        slots = {aid: MagicMock() for aid in agent_ids}
        translator.get_slots_to_allocate = AsyncMock(return_value=(start_time, slots))
        translator.submit = AsyncMock(side_effect=[ok_result("agent-1"), ok_result("agent-2")])
        translator.getResult = AsyncMock(side_effect=[ok_result("agent-1"), ok_result("agent-2")])
        handle = MagicMock()

        run(translator.translate_request("exp-1", exp, {}, agent_ids, handle_result=handle))

        assert handle.call_count == 2
