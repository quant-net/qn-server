import datetime
import errno
import json
import logging
import os
import os.path
import re
import signal
import subprocess
import threading
import time
import requests
from typing import Optional, Tuple
from functools import wraps
from uuid import uuid4 as uuid
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlencode, quote, parse_qsl, urlunparse

from quantnet_controller.common.extra import import_extras

EXTRA_MODULES = import_extras(["paramiko"])

if EXTRA_MODULES["paramiko"]:
    try:
        from paramiko import RSAKey

        RSAKey
    except Exception:
        EXTRA_MODULES["paramiko"] = False

if TYPE_CHECKING:
    from typing import Callable, TypeVar

    T = TypeVar("T")

# RFC 1123 (ex RFC 822)
DATE_FORMAT = "%a, %d %b %Y %H:%M:%S UTC"


def invert_dict(d):
    """
    Invert the dictionary.
    CAUTION: this function is not deterministic unless the input dictionary is one-to-one mapping.

    :param d: source dictionary
    :returns: dictionary {value: key for key, value in d.items()}
    """
    return {value: key for key, value in d.items()}


def replace_resource_uri(uri, new_part):
    parsed_uri = urlparse(uri)
    path_parts = parsed_uri.path.split('/')
    path_parts[-1] = new_part
    new_path = '/'.join(path_parts)
    return urlunparse(parsed_uri._replace(path=new_path))


def get_uri_path(uri):
    return urlparse(uri).path.lstrip("/")


def build_url(url, path=None, params=None, doseq=False):
    """
    utitily function to build an url for requests.

    If the optional parameter doseq is evaluates to True, individual key=value pairs
    separated by '&' are generated for each element of the value sequence for the key.
    """
    complete_url = url
    if path is not None:
        complete_url += "/" + path
    if params is not None:
        complete_url += "?"
        if isinstance(params, str):
            complete_url += quote(params)
        else:
            complete_url += urlencode(params, doseq=doseq)
    return complete_url


def generate_uuid():
    return str(uuid()).replace("-", "").lower()


def generate_uuid_bytes():
    return uuid().bytes


def str_to_date(string):
    """Converts a RFC-1123 string to the corresponding datetime value.

    :param string: the RFC-1123 string to convert to datetime value.
    """
    return datetime.datetime.strptime(string, DATE_FORMAT) if string else None


def val_to_space_sep_str(vallist):
    """Converts a list of values into a string of space separated values

    :param vallist: the list of values to to convert into string
    :return: the string of space separated values or the value initially passed as parameter
    """
    try:
        if isinstance(vallist, list):
            return str(" ".join(vallist))
        else:
            return str(vallist)
    except RuntimeError:
        return str("")


def date_to_str(date: datetime.datetime) -> Optional[str]:
    """Converts a datetime value to the corresponding RFC-1123 string.

    :param date: the datetime value to convert.
    """
    return datetime.datetime.strftime(date, DATE_FORMAT) if date else None


def datetime_parser(dct):
    """datetime parser"""
    for k, v in list(dct.items()):
        if isinstance(v, str) and re.search(" UTC", v):
            try:
                dct[k] = datetime.datetime.strptime(v, DATE_FORMAT)
            except Exception:
                pass
    return dct


def parse_response(data):
    """
    JSON render function
    """
    if hasattr(data, "decode"):
        data = data.decode("utf-8")

    return json.loads(data, object_hook=datetime_parser)


def execute(cmd) -> Tuple[int, str, str]:
    """
    Executes a command in a subprocess. Returns a tuple
    of (exitcode, out, err), where out is the string output
    from stdout and err is the string output from stderr when
    executing the command.

    :param cmd: Command string to execute
    """

    process = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    result = process.communicate()
    (out, err) = result
    exitcode = process.returncode
    return exitcode, out.decode(encoding="utf-8"), err.decode(encoding="utf-8")


def pid_exists(pid):
    """
    Check whether pid exists in the current process table.
    UNIX only.
    """
    if pid < 0:
        return False
    if pid == 0:
        # According to "man 2 kill" PID 0 refers to every process
        # in the process group of the calling process.
        # On certain systems 0 is a valid PID but we have no way
        # to know that in a portable fashion.
        raise ValueError("invalid PID 0")
    try:
        os.kill(pid, 0)
    except OSError as err:
        if err.errno == errno.ESRCH:
            # ESRCH == No such process
            return False
        elif err.errno == errno.EPERM:
            # EPERM clearly means there's a process to deny access to
            return True
        else:
            # According to "man 2 kill" possible error values are
            # (EINVAL, EPERM, ESRCH)
            raise
    else:
        return True


def sizefmt(num, human=True):
    """
    Print human readable file sizes
    """
    if num is None:
        return "0.0 B"
    try:
        num = int(num)
        if human:
            for unit in ["", "k", "M", "G", "T", "P", "E", "Z"]:
                if abs(num) < 1000.0:
                    return f"{num} {unit}B"
                num /= 1000.0
            return f"{num} YB"
        else:
            return str(num)
    except OverflowError:
        return "Inf"


def send_trace(trace, trace_endpoint, user_agent, retries=5):
    """
    Send the given trace to the trace endpoint

    :param trace: the trace dictionary to send
    :param trace_endpoint: the endpoint where the trace should be send
    :param user_agent: the user agent sending the trace
    :param retries: the number of retries if sending fails
    :return: 0 on success, 1 on failure
    """
    if user_agent.startswith("pilot"):
        return 0
    for dummy in range(retries):
        try:
            requests.post(trace_endpoint + "/traces/", verify=False, data=json.dumps(trace))
            return 0
        except Exception:
            pass
    return 1


def add_url_query(url, query):
    """
    Add a new dictionary to URL parameters

    :param url: The existing URL
    :param query: A dictionary containing key/value pairs to be added to the URL
    :return: The expanded URL with the new query parameters
    """

    url_parts = list(urlparse(url))
    mod_query = dict(parse_qsl(url_parts[4]))
    mod_query.update(query)
    url_parts[4] = urlencode(mod_query)
    return urlunparse(url_parts)


def get_thread_with_periodic_running_function(interval, action, graceful_stop):
    """
    Get a thread where a function runs periodically.

    :param interval: Interval in seconds when the action fucntion should run.
    :param action: Function, that should run periodically.
    :param graceful_stop: Threading event used to check for graceful stop.
    """

    def start():
        while not graceful_stop.is_set():
            starttime = time.time()
            action()
            time.sleep(interval - ((time.time() - starttime)))

    t = threading.Thread(target=start)
    return t


def run_cmd_process(cmd, timeout=3600):
    """
    shell command parser with timeout

    :param cmd: shell command as a string
    :param timeout: in seconds

    :return: stdout xor stderr, and errorcode
    """

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, preexec_fn=os.setsid, universal_newlines=True
    )

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            # Kill the whole process group since we're using shell=True.
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            stdout, stderr = process.communicate()

    if not stderr:
        stderr = ""
    if not stdout:
        stdout = ""
    if stderr and stderr != "":
        stdout += " Error: " + stderr
    if process:
        returncode = process.returncode
    else:
        returncode = 1
    if returncode != 1 and "Command time-out" in stdout:
        returncode = 1
    if returncode is None:
        returncode = 0

    return returncode, stdout


def setup_logger(config=None, module_name=None, logger_name=None, logger_level=None, verbose=False):
    """
    Factory method to set logger with handlers.
    :param module_name: __name__ of the module that is calling this method
    :param logger_name: name of the logger, typically name of the module.
    :param logger_level: if not given, fetched from config.
    :param verbose: verbose option set to False by default.
    """

    # helper method for cfg check
    def _force_cfg_log_level(cfg_option):
        if not config:
            return False
        cfg_forced_modules = config.get(
            "logging", cfg_option, raise_exception=False, default=None, clean_cached=True, check_config_table=False
        )
        if cfg_forced_modules:
            if re.match(str(cfg_forced_modules), module_name):
                return True
        return False

    # creating log
    if not logger_name:
        if not module_name:
            logger_name = "usr"
        else:
            logger_name = module_name.split(".")[-1]
    logger = logging.getLogger(logger_name)

    # extracting the log level
    if not logger_level:
        logger_level = logging.INFO
        if verbose:
            logger_level = logging.DEBUG

        # overriding by the config
        cfg_levels = (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR)
        for level in cfg_levels:
            cfg_opt = "forceloglevel" + logging.getLevelName(level)
            if _force_cfg_log_level(cfg_opt):
                logger_level = level

    # setting the log level
    logger.setLevel(logger_level)

    # preferred logger handling
    def add_handler(logger):
        hdlr = logging.StreamHandler()

        def emit_decorator(fnc):
            def func(*args):
                if "QNET_LOGGING_FORMAT" not in os.environ:
                    levelno = args[0].levelno
                    format_str = "%(asctime)s\t%(levelname)s\t%(message)s\033[0m"
                    if levelno >= logging.CRITICAL:
                        color = "\033[31;1m"
                    elif levelno >= logging.ERROR:
                        color = "\033[31;1m"
                    elif levelno >= logging.WARNING:
                        color = "\033[33;1m"
                    elif levelno >= logging.INFO:
                        color = "\033[32;1m"
                    elif levelno >= logging.DEBUG:
                        color = "\033[36;1m"
                        format_str = "%(asctime)s\t%(levelname)s\t%(filename)s\t%(message)s\033[0m"
                    else:
                        color = "\033[0m"
                    formatter = logging.Formatter(f"{color}{format_str}")
                else:
                    formatter = logging.Formatter(os.environ["QNET_LOGGING_FORMAT"])
                hdlr.setFormatter(formatter)
                return fnc(*args)

            return func

        hdlr.emit = emit_decorator(hdlr.emit)
        logger.addHandler(hdlr)

    # setting handler and formatter
    if not logger.handlers:
        add_handler(logger)

    return logger


def daemon_sleep(start_time, sleep_time, graceful_stop, logger=logging.log):
    """Sleeps a daemon the time provided by sleep_time"""
    end_time = time.time()
    time_diff = end_time - start_time
    if time_diff < sleep_time:
        logger(logging.INFO, "Sleeping for a while :  %s seconds", (sleep_time - time_diff))
        graceful_stop.wait(sleep_time - time_diff)


class retry:
    """Retry callable object with configuragle number of attempts"""

    def __init__(self, func, *args, **kwargs):
        """
        :param func: a method that should be executed with retries
        :param args: parametres of the func
        :param kwargs: key word arguments of the func
        """
        self.func, self.args, self.kwargs = func, args, kwargs

    def __call__(self, mtries=3, logger=logging.log):
        """
        :param mtries: maximum number of attempts to execute the function
        :param logger: preferred logger
        """
        attempt = mtries
        while attempt > 1:
            try:
                if logger:
                    logger(logging.DEBUG, f"{self.func.__name__}: Attempt {mtries - attempt + 1}")
                return self.func(*self.args, **self.kwargs)
            except Exception as e:
                if logger:
                    logger(logging.DEBUG, "f{self.func.__name__}: Attempt failed {mtries - attempt + 1}")
                    logger(logging.DEBUG, str(e))
                attempt -= 1
        return self.func(*self.args, **self.kwargs)


class PriorityQueue:
    """
    Heap-based [1] priority queue which supports priority update operations

    It is used as a dictionary: pq['element'] = priority
    The element with the highest priority can be accessed with pq.top() or pq.pop(),
    depending on the desire to keep it in the heap or not.

    [1] https://en.wikipedia.org/wiki/Heap_(data_structure)
    """

    class ContainerSlot:
        def __init__(self, position, priority):
            self.pos = position
            self.prio = priority

    def __init__(self):
        self.heap = []
        self.container = {}
        self.empty_slots = []

    def __len__(self):
        return len(self.heap)

    def __getitem__(self, item):
        return self.container[item].prio

    def __setitem__(self, key, value):
        if key in self.container:
            existing_prio = self.container[key].prio
            self.container[key].prio = value
            if value < existing_prio:
                self._priority_decreased(key)
            elif existing_prio < value:
                self._priority_increased(key)
        else:
            self.heap.append(key)
            self.container[key] = self.ContainerSlot(position=len(self.heap) - 1, priority=value)
            self._priority_decreased(key)

    def __contains__(self, item):
        return item in self.container

    def top(self):
        return self.heap[0]

    def pop(self):
        item = self.heap[0]
        self.container.pop(item)

        tmp_item = self.heap.pop()
        if self.heap:
            self.heap[0] = tmp_item
            self.container[tmp_item].pos = 0
            self._priority_increased(tmp_item)
        return item

    def _priority_decreased(self, item):
        heap_changed = False

        pos = self.container[item].pos
        pos_parent = (pos - 1) // 2
        while pos > 0 and self.container[self.heap[pos]].prio < self.container[self.heap[pos_parent]].prio:
            tmp_item, parent = self.heap[pos], self.heap[pos_parent] = self.heap[pos_parent], self.heap[pos]
            self.container[tmp_item].pos, self.container[parent].pos = (
                self.container[parent].pos,
                self.container[tmp_item].pos,
            )

            pos = pos_parent
            pos_parent = (pos - 1) // 2

            heap_changed = True
        return heap_changed

    def _priority_increased(self, item):
        heap_changed = False
        heap_len = len(self.heap)
        pos = self.container[item].pos
        pos_child1 = 2 * pos + 1
        pos_child2 = 2 * pos + 2

        heap_restored = False
        while not heap_restored:
            # find minimum between item, child1, and child2
            if (
                pos_child1 < heap_len
                and self.container[self.heap[pos_child1]].prio < self.container[self.heap[pos]].prio
            ):
                pos_min = pos_child1
            else:
                pos_min = pos
            if (
                pos_child2 < heap_len
                and self.container[self.heap[pos_child2]].prio < self.container[self.heap[pos_min]].prio
            ):
                pos_min = pos_child2

            if pos_min != pos:
                _, tmp_item = self.heap[pos_min], self.heap[pos] = self.heap[pos], self.heap[pos_min]
                self.container[tmp_item].pos = pos

                pos = pos_min
                pos_child1 = 2 * pos + 1
                pos_child2 = 2 * pos + 2

                heap_changed = True
            else:
                heap_restored = True

        self.container[self.heap[pos]].pos = pos
        return heap_changed


def retrying(
    retry_on_exception: "Callable[[Exception], bool]", wait_fixed: int, stop_max_attempt_number: int
) -> "Callable[[Callable[..., T]], Callable[..., T]]":
    """
    Decorator which retries a function multiple times on certain types of exceptions.
    :param retry_on_exception: Function which takes an exception as argument and returns True if we must retry on this
    exception
    :param wait_fixed: the amount of time to wait in-between two tries
    :param stop_max_attempt_number: maximum number of allowed attempts
    """

    def _decorator(fn):
        @wraps(fn)
        def _wrapper(*args, **kwargs):
            attempt = 0
            while True:
                attempt += 1
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    if attempt >= stop_max_attempt_number:
                        raise
                    if not retry_on_exception(e):
                        raise
                time.sleep(wait_fixed / 1000.0)

        return _wrapper

    return _decorator
