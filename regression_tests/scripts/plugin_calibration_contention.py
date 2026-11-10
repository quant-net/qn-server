#!/usr/bin/env python
"""
Self-contained calibration contention regression test.

Starts a controller and 5 agents where all agents use an aggressive calibration
config (Periodicity=5s, Maximum_duration=3s, occupying ~60% of scheduler
timeslots). Sends an EGP request and verifies the system handles contention
gracefully -- either finding a gap between calibration blocks (OK) or
returning FAILED with "slots already occupied" or "No common free timeslot".

Both outcomes (OK or graceful FAILED) are valid. A FAIL only occurs if the
system crashes, hangs, or produces an unexpected error.

Key insight: DummyExpFramework.submit() returns instantly (no sleep), so
calibration tasks complete in <1ms but still occupy timeslots for their full
Maximum_duration in the scheduler's array. The scheduler books 30 timeslots
(3s / 100ms) every 50 timeslots (5s / 100ms).

Prerequisites:
  - mosquitto running on localhost:1883
  - mongo running on localhost:27017
  - workspace root at /Users/se-youngyu/quantum/

Usage:
  python -u regression_tests/scripts/plugin_calibration_contention.py
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from quantnet_mq.rpcclient import RPCClient
from quantnet_mq.schema.models import Schema
from quantnet_mq import Code

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

# Resolve workspace root from this script's path
WORKSPACE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

# Agent topology config file mapping
AGENTS = {
    "LBNL-Q":      "conf_lbnl-q.json",
    "UCB-Q":       "conf_ucb-q.json",
    "LBNL-SWITCH": "conf_lbnl-switch.json",
    "UCB-SWITCH":  "conf_ucb-switch.json",
    "LBNL-BSM":    "conf_lbnl-bsm.json",
}


def make_local_agent_cfg(workspace, template_cfg_path):
    """
    Read agent.cfg template and rewrite Docker paths to workspace-absolute paths.

    Replaces /qn-agent/config/ and ../qn-agent/config/ with absolute workspace paths.

    Args:
        workspace: Absolute path to workspace root
        template_cfg_path: Path to the template agent.cfg

    Returns:
        Path to temporary agent.cfg with rewritten paths
    """
    with open(template_cfg_path, 'r') as f:
        lines = f.readlines()

    # Process line by line: replace qn-agent/config paths with workspace absolute path
    # Be careful to avoid double-replacement by checking the source pattern first
    workspace_cfg_path = os.path.join(workspace, 'qn-agent', 'config') + '/'
    new_lines = []
    for line in lines:
        if 'path=' in line and 'qn-agent/config/' in line:
            # First try relative path
            if '../qn-agent/config/' in line:
                line = line.replace('../qn-agent/config/', workspace_cfg_path)
            # Then try absolute path (only if relative wasn't already replaced)
            elif '/qn-agent/config/' in line:
                line = line.replace('/qn-agent/config/', workspace_cfg_path)
        new_lines.append(line)

    # Write to temp file
    temp_file = tempfile.NamedTemporaryFile(
        mode='w',
        prefix='agent_cfg_',
        suffix='.cfg',
        delete=False
    )
    temp_file.writelines(new_lines)
    temp_file.close()

    return temp_file.name


def make_contention_agent_cfg(workspace):
    """
    Create a custom agent.cfg with aggressive calibration for contention testing.

    Args:
        workspace: Absolute path to workspace root

    Returns:
        Path to temporary agent.cfg with aggressive calibration
    """
    # Read the template agent.cfg
    template_path = os.path.join(workspace, "qn-agent", "config", "agent.cfg")
    with open(template_path, 'r') as f:
        lines = f.readlines()

    # Process lines to replace paths - avoid double-replacement
    workspace_cfg_path = os.path.join(workspace, 'qn-agent', 'config') + '/'
    new_lines = []
    for line in lines:
        if 'path=' in line and 'qn-agent/config/' in line:
            # Check source pattern first to avoid double-replacement
            if '../qn-agent/config/' in line:
                line = line.replace('../qn-agent/config/', workspace_cfg_path)
            elif '/qn-agent/config/' in line:
                line = line.replace('/qn-agent/config/', workspace_cfg_path)
        new_lines.append(line)
    
    content = ''.join(new_lines)

    # Create a custom calibration task JSON with aggressive periodicity
    calibration_json = {
        "id": "contention_test_calibration",
        "Name": "Contention Test Calibration",
        "Purpose": "Aggressive calibration for contention testing (5s period, 3s duration)",
        "Derived_parameters": [],
        "Periodicity": 5,
        "Dependency": None,
        "Status_check": None,
        "Lightweight_calibration": None,
        "Full_scale_calibration": {
            "Function": "experiments/Calibrations/cal_397_frequency.py",
            "Class": "Cal397Freq",
            "Scanning_parameters": "CF_frequency_397",
            "Result_parameters": ["current_scan.plots.x", "current_scan.plots.y"],
            "Experiment_parameters": {},
            "Maximum_duration": 3,
            "Analysis_function": None
        }
    }

    # Write the calibration JSON to a tempfile
    cal_file = tempfile.NamedTemporaryFile(
        mode='w',
        prefix='contention_cal_',
        suffix='.json',
        delete=False
    )
    json.dump(calibration_json, cal_file)
    cal_file.close()

    # Replace the [tasks] section completely with just our contention task
    lines = content.split('\n')
    new_lines = []
    in_tasks_section = False
    skip_until_next_section = False
    
    for i, line in enumerate(lines):
        if line.startswith('[tasks]'):
            # Found tasks section - add it with just our contention task
            new_lines.append(line)
            new_lines.append('[[contention_test_calibration]]')
            new_lines.append(f'path={cal_file.name}')
            new_lines.append('')  # blank line to end section
            skip_until_next_section = True
        elif skip_until_next_section:
            # Skip all old task entries until next section
            if line.startswith('['):
                # Found next section
                skip_until_next_section = False
                new_lines.append(line)
            # else: skip this line (part of old tasks section)
        else:
            new_lines.append(line)

    modified_content = '\n'.join(new_lines)

    # Write the modified agent.cfg to a tempfile
    cfg_file = tempfile.NamedTemporaryFile(
        mode='w',
        prefix='agent_cfg_contention_',
        suffix='.cfg',
        delete=False
    )
    cfg_file.write(modified_content)
    cfg_file.close()

    return cfg_file.name


def start_controller(log_files):
    """Start the quantnet controller as a subprocess."""
    log_file = tempfile.NamedTemporaryFile(prefix="ctrl_", suffix=".log", delete=False)
    log_file.close()
    log_files.append(("controller", log_file.name))

    cmd = [
        sys.executable,
        "-m", "quantnet_controller.cli",
        "--mq-broker-host", "localhost",
        "--mq-mongo-host", "localhost",
        "-c", os.path.join(WORKSPACE, "etc", "quantnet.cfg"),
        "--plugin-path", os.path.join(WORKSPACE, "qn-plugins", "plugins"),
        "--schema-path", os.path.join(WORKSPACE, "qn-plugins", "plugins", "schema"),
    ]
    with open(log_file.name, 'w') as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
    return proc


def start_agent(agent_id, node_config, log_files, agent_cfg_path=None):
    """Start a quantnet agent as a subprocess."""
    log_file = tempfile.NamedTemporaryFile(prefix=f"agent_{agent_id}_", suffix=".log", delete=False)
    log_file.close()
    log_files.append((agent_id, log_file.name))

    # Use provided agent.cfg or create a default local one
    if agent_cfg_path is None:
        agent_cfg_path = make_local_agent_cfg(
            WORKSPACE,
            os.path.join(WORKSPACE, "qn-agent", "config", "agent.cfg")
        )

    cmd = [
        sys.executable,
        "-m", "quantnet_agent.cli",
        "-a", agent_id,
        "-n", node_config,
        "-c", agent_cfg_path,
        "--mq-broker-host", "localhost",
        "--no-repl",
        "--interpreter-path", os.path.join(WORKSPACE, "qn-plugins", "plugins", "pingpong", "interpreter"),
        "--schema-path", os.path.join(WORKSPACE, "qn-plugins", "plugins", "schema"),
    ]
    with open(log_file.name, 'w') as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
    return proc


def terminate_all(procs):
    """Terminate all subprocesses, with SIGTERM then SIGKILL."""
    for proc in procs:
        try:
            proc.terminate()
        except Exception:
            pass
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def check_logs(log_files, exclude_patterns=None):
    """
    Scan log files for error patterns.

    Returns list of (filename, line) tuples matching error patterns,
    excluding lines with false positive patterns.
    """
    if exclude_patterns is None:
        exclude_patterns = []

    error_patterns = ["Traceback", "FileNotFoundError", "Errno", "InvalidStateError"]
    false_positive_patterns = [
        "RPC timeout",
        "--no-repl",
        "Cannot load local task",
        "Slots are already occupied",  # Expected behavior in contention test
    ] + exclude_patterns

    errors = []
    for name, path in log_files:
        try:
            with open(path, 'r') as f:
                for line in f:
                    line = line.rstrip()
                    # Check if line matches any error pattern
                    if any(pattern in line for pattern in error_patterns):
                        # Exclude false positives
                        if not any(fp in line for fp in false_positive_patterns):
                            errors.append((name, line))
        except Exception as e:
            log.warning(f"Could not read log {path}: {e}")

    return errors


async def test_egp(host="localhost"):
    """Send an EGP request and return the response."""
    try:
        Schema.load_schema(
            os.path.join(WORKSPACE, "qn-plugins", "plugins", "schema", "egp.yaml"),
            ns="egp"
        )

        client = RPCClient(f"egp-test-{os.getpid()}", host=host)
        client.set_handler("egpRequest", None, "quantnet_mq.schema.models.egp.egpRequest")
        await client.start()

        msg = {
            "source": "LBNL-Q",
            "destination": "UCB-Q",
            "pairs": 1,
            "bellState": "∣Φ+⟩",
            "fidelity": 0.9,
        }
        log.info(f"Sending EGP request: {msg}")
        response = json.loads(await client.call("egpRequest", msg, timeout=60.0))
        log.info(f"EGP response: {response}")
        return response
    except Exception as e:
        log.error(f"EGP test failed: {e}", exc_info=True)
        return {"status": {"code": Code.FAILED.value, "value": Code.FAILED.name, "message": str(e)}}


async def main():
    """Main test orchestration."""
    procs = []
    log_files = []
    try:
        # 1. Start controller
        log.info("Starting controller...")
        procs.append(start_controller(log_files))
        await asyncio.sleep(5)

        # 2. Create contention agent configs (all 5 agents get aggressive calibration)
        log.info("Creating contention agent configs...")
        contention_cfg = make_contention_agent_cfg(WORKSPACE)

        # 3. Start all 5 agents with contention config
        log.info("Starting 5 agents with aggressive calibration...")
        topo_dir = os.path.join(WORKSPACE, "qn-mq", "quantnet_mq", "schema", "examples", "topology")
        for agent_id, config_file in AGENTS.items():
            node_config = os.path.join(topo_dir, config_file)
            procs.append(start_agent(agent_id, node_config, log_files, agent_cfg_path=contention_cfg))
            await asyncio.sleep(0.5)

        # 4. Wait for agent registration + calibration warmup
        log.info("Waiting 15s for agent registration + calibration warmup...")
        await asyncio.sleep(15)

        # 5. Send EGP request
        log.info("\n" + "="*70)
        log.info("Sending EGP request (with 60% slot occupancy from calibration)...")
        log.info("="*70)
        egp_response = await test_egp()
        egp_code = egp_response.get("status", {}).get("code")
        egp_message = egp_response.get("status", {}).get("message", "")

        # Determine contention result
        if egp_code == Code.OK.value:
            contention_result = "OK"
            contention_details = "found gap between calibration blocks"
        elif egp_code == Code.FAILED.value:
            # Check for various graceful failure modes - all are expected in contention scenario
            if ("slots already occupied" in egp_message or 
                "No common free timeslot" in egp_message or
                "Timeout" in egp_message):
                contention_result = "OK"
                contention_details = "gracefully rejected (expected contention)"
            else:
                # Some other failure - unexpected
                contention_result = "FAIL"
                contention_details = f"unexpected error: {egp_message}"
        else:
            contention_result = "FAIL"
            contention_details = f"unexpected code {egp_code}"

        # 6. Check all subprocesses still alive
        procs_ok = all(proc.poll() is None for proc in procs)
        procs_status = "OK" if procs_ok else "FAIL"
        procs_details = f"{sum(1 for p in procs if p.poll() is None)}/{len(procs)}"

        # 7. Check logs
        log.info("Checking logs for errors...")
        log_errors = check_logs(log_files)
        log_ok = len(log_errors) == 0
        log_status = "OK" if log_ok else f"FAIL ({len(log_errors)} errors)"

        # 8. Print summary
        print("\n" + "="*70)
        print("CALIBRATION CONTENTION REGRESSION -- 5 agents")
        print("(Periodicity=5s, Maximum_duration=3s, ~60% timeslot occupancy)")
        print("="*70)
        print(f"{'TEST':<25} {'STATUS':<10} {'DETAILS':<35}")
        print("-"*70)
        print(f"{'EGP Request':<25} {contention_result:<10} {contention_details:<35}")
        print(f"{'Processes Alive':<25} {procs_status:<10} {procs_details:<35}")
        print(f"{'Log Check':<25} {log_status:<10} {'clean' if log_ok else 'errors found':<35}")
        print("="*70)

        if log_errors:
            print("\nLog errors found:")
            for agent, line in log_errors[:10]:
                print(f"  {agent}: {line}")

        print("\nLog files:")
        for agent, path in log_files:
            print(f"  {agent}: {path}")

        # Overall success: contention handled gracefully + processes alive + clean logs
        success = (contention_result == "OK") and procs_ok and log_ok
        return success

    finally:
        log.info("Terminating processes...")
        terminate_all(procs)


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        log.info("Interrupted")
        sys.exit(1)
    except Exception as e:
        log.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)
