#!/usr/bin/env python
"""
Self-contained EGP/DQC plugin regression test — minimal topology (5 agents).

Starts a controller and 5 agents (2 QNodes, 2 Switches, 1 BSM) as local Python
subprocesses, sends EGP and DQC RPC requests, verifies response codes and log
cleanliness.

Prerequisites:
  - mosquitto running on localhost:1883
  - mongo running on localhost:27017
  - workspace root at /Users/se-youngyu/quantum/
  - qn-mq, qn-server, qn-agent, qn-plugins installed in shared venv

Usage:
  python -u regression_tests/scripts/plugin_minimal.py
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


def make_local_agent_cfg(workspace, template_cfg_path):
    """
    Read agent.cfg template and rewrite Docker paths to workspace-absolute paths.
    
    Replaces /qn-agent/config/ with <workspace>/qn-agent/config/ for all task file paths.
    
    Args:
        workspace: Absolute path to workspace root
        template_cfg_path: Path to the template agent.cfg
    
    Returns:
        Path to temporary agent.cfg with rewritten paths
    """
    with open(template_cfg_path, 'r') as f:
        content = f.read()
    
    # Replace Docker absolute paths with workspace-absolute paths
    content = content.replace(
        '/qn-agent/config/',
        os.path.join(workspace, 'qn-agent', 'config') + '/'
    )
    
    # Write to temp file
    temp_file = tempfile.NamedTemporaryFile(
        mode='w',
        prefix='agent_cfg_',
        suffix='.cfg',
        delete=False
    )
    temp_file.write(content)
    temp_file.close()
    
    return temp_file.name

# Resolve workspace root from this script's path
WORKSPACE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

# Agent topology config file mapping — minimal viable topology for EGP/DQC
AGENTS = {
    "LBNL-Q":      "conf_lbnl-q.json",
    "UCB-Q":       "conf_ucb-q.json",
    "LBNL-SWITCH": "conf_lbnl-switch.json",
    "UCB-SWITCH":  "conf_ucb-switch.json",
    "LBNL-BSM":    "conf_lbnl-bsm.json",
}


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


def start_agent(agent_id, node_config, log_files):
    """Start a quantnet agent as a subprocess."""
    log_file = tempfile.NamedTemporaryFile(prefix=f"agent_{agent_id}_", suffix=".log", delete=False)
    log_file.close()
    log_files.append((agent_id, log_file.name))
    
    # Create a local agent.cfg with workspace-absolute paths
    local_agent_cfg = make_local_agent_cfg(
        WORKSPACE,
        os.path.join(WORKSPACE, "qn-agent", "config", "agent.cfg")
    )
    
    cmd = [
        sys.executable,
        "-m", "quantnet_agent.cli",
        "-a", agent_id,
        "-n", node_config,
        "-c", local_agent_cfg,
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
    false_positive_patterns = ["RPC timeout", "--no-repl", "Cannot load local task"] + exclude_patterns
    
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


async def test_dqc(host="localhost"):
    """Send a DQC request and return the response."""
    try:
        # Check if qnpack is available
        try:
            import qnpack  # noqa: F401
        except ImportError:
            log.warning("qnpack not installed; skipping DQC test")
            return {"status": {"code": Code.FAILED.value, "value": Code.FAILED.name, "message": "qnpack not installed"}}
        
        Schema.load_schema(
            os.path.join(WORKSPACE, "qn-plugins", "plugins", "schema", "dqc.yaml"),
            ns="dqc"
        )
        
        client = RPCClient(f"dqc-test-{os.getpid()}", host=host)
        client.set_handler("dqcRequest", None, "quantnet_mq.schema.models.dqc.dqcRequest")
        await client.start()
        
        circuit_path = os.path.join(
            WORKSPACE, "qnpack-public", "qnpack", "dqc", "commands", "grover_4_2qpu.txt"
        )
        msg = {"circuit_mode": "tket", "circuit_file": circuit_path}
        log.info(f"Sending DQC request: circuit_mode=tket, circuit_file={circuit_path}")
        response = json.loads(await client.call("dqcRequest", msg, timeout=120.0))
        log.info(f"DQC response status: {response.get('status')}")
        return response
    except Exception as e:
        log.error(f"DQC test failed: {e}", exc_info=True)
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
        
        # 2. Start all 5 agents
        log.info("Starting agents...")
        topo_dir = os.path.join(WORKSPACE, "qn-mq", "quantnet_mq", "schema", "examples", "topology")
        for agent_id, config_file in AGENTS.items():
            node_config = os.path.join(topo_dir, config_file)
            procs.append(start_agent(agent_id, node_config, log_files))
            await asyncio.sleep(0.5)
        
        # 3. Wait for agent registration
        log.info("Waiting for agent registration (15s)...")
        await asyncio.sleep(15)
        
        # 4. Run EGP test
        log.info("\n" + "="*70)
        log.info("Running EGP test...")
        egp_response = await test_egp()
        egp_ok = egp_response.get("status", {}).get("code") == Code.OK.value
        egp_status = "OK" if egp_ok else "FAIL"
        egp_details = egp_response.get("status", {}).get("message", "unknown")
        
        # 5. Run DQC test
        log.info("\n" + "="*70)
        log.info("Running DQC test...")
        dqc_response = await test_dqc()
        dqc_ok = dqc_response.get("status", {}).get("code") == Code.OK.value
        dqc_status = "OK" if dqc_ok else "FAIL"
        dqc_details = dqc_response.get("status", {}).get("message", "unknown")
        
        # 6. Check logs
        log.info("\n" + "="*70)
        log.info("Checking logs for errors...")
        log_errors = check_logs(log_files)
        log_ok = len(log_errors) == 0
        log_status = "OK" if log_ok else f"FAIL ({len(log_errors)} errors)"
        
        # 7. Print summary
        print("\n" + "="*70)
        print("EGP/DQC PLUGIN REGRESSION — MINIMAL TOPOLOGY (5 agents)")
        print("="*70)
        print(f"{'TEST':<20} {'STATUS':<10} {'DETAILS':<40}")
        print("-"*70)
        print(f"{'EGP Request':<20} {egp_status:<10} {egp_details:<40}")
        print(f"{'DQC Request':<20} {dqc_status:<10} {dqc_details:<40}")
        print(f"{'Log Check':<20} {log_status:<10} {'clean' if log_ok else 'errors found':<40}")
        print("="*70)
        
        if log_errors:
            print("\nLog errors found:")
            for agent, line in log_errors[:10]:
                print(f"  {agent}: {line}")
        
        # 8. Print log file paths
        print("\nLog files:")
        for agent, path in log_files:
            print(f"  {agent}: {path}")
        
        # Return overall success
        success = egp_ok and dqc_ok and log_ok
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
