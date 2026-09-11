import os
import enum
import glob
import yaml
import json
from py_landlock import Landlock, AccessFs
from pathlib import Path
from src.logger import get_logger

logger = get_logger(__name__)

def apply_security_policy(path):
    try:
        if path:
            policy = FileSystemPolicy()
            policy.load_file(path)
            policy.apply()
        else:
            logger.warning("SecurityPolicyPath is not set")
    except Exception as e:
        logger.exception(f"Unexpected exception: {e}")
        raise

def get_allowed_policy_paths(path) -> str:
    """
    Retrieves and serializes the allowed filesystem paths from the security policy.

    This function is exposed to the agent as a skill (`get-io-policy`). It reads the 
    Landlock security policy configuration and returns the permitted base paths 
    for read-only and read-write operations in JSON format. This allows the LLM 
    to proactively check path permissions before attempting File I/O operations.

    Args:
        path (str | Any): The file path to the security policy YAML file. 
                          Can be a raw string or a MeTTa symbol (which will be parsed to a string).

    Returns:
        str: A JSON-formatted string containing two keys: 'read_only' and 'read_write', 
             with lists of allowed directory paths.
             If the path is missing or an error occurs, returns a descriptive error string.
    """
    try:
        path = str(path or "").strip().strip('"')
        if path:
            policy = FileSystemPolicy()
            policy.load_file(path)
            return json.dumps({
                'read_only': [str(p) for p in policy._read_only],
                'read_write': [str(p) for p in policy._read_write]
            })
        else:
            logger.warning("SecurityPolicyPath is not set")
            return "Could not retrieve policy: policy is not set"
    except Exception as e:
        logger.exception(
            f"Could not retrieve a policy due to unexpected exception: {e}"
        )
        return "Could not retrieve a policy: unexpected exception"

class LandLockCompatibility(enum.Enum):
    BEST_EFFORT = 0
    HARD_REQUIREMENT = 1

class FileSystemPolicy:

    READ_ONLY_DIR_ACCESS = AccessFs.READ_DIR | AccessFs.READ_FILE
    READ_ONLY_FILE_ACCESS = AccessFs.READ_FILE
    READ_WRITE_DIR_ACCESS = (AccessFs.READ_FILE | AccessFs.READ_DIR
                             | AccessFs.WRITE_FILE | AccessFs.TRUNCATE
                             | AccessFs.MAKE_REG | AccessFs.MAKE_DIR
                             | AccessFs.MAKE_SYM | AccessFs.REMOVE_FILE
                             | AccessFs.REMOVE_DIR | AccessFs.MAKE_FIFO
                             | AccessFs.MAKE_SOCK)
    READ_WRITE_FILE_ACCESS = (AccessFs.READ_FILE | AccessFs.WRITE_FILE |
                              AccessFs.TRUNCATE)
    DEVICE_ACCESS = AccessFs.READ_FILE | AccessFs.WRITE_FILE | AccessFs.IOCTL_DEV

    def __init__(self):
        self._compatibility = LandLockCompatibility.BEST_EFFORT
        self._read_only = []
        self._read_write = []
        self._device_access = []

    def load_file(self, path: str|Path):
        logger.info(f"Loading policy from file {path}")
        policy = None
        with open(path, "r") as f:
            policy = yaml.safe_load(f)
        self.load_dict(policy)

    def load_str(self, policy: str):
        policy = yaml.safe_load(policy)
        self.load_dict(policy)

    def load_dict(self, policy: dict):
        version = policy.get('version')
        assert version == 1

        self._compatibility = LandLockCompatibility.BEST_EFFORT
        ll = policy.get('landlock')
        if ll:
            comp = ll.get('compatibility')
            if comp:
                self._compatibility = LandLockCompatibility[comp.upper()]

        fs = policy.get('filesystem_policy')

        ro = []
        rw = []
        if fs:
            ro = fs.get('read_only', [])
            if ro is None:
                ro = []
            rw = fs.get('read_write', [])
            if rw is None:
                ro = []
            if policy.get('include_workdir'):
                rw.append(os.getcwd())
        self._read_only = [Path(f'{p}') for p in ro]
        self._read_write = [Path(f'{p}') for p in rw]
        self._device_access = list(fs.get('device_access', []) or []) if fs else []

    def _resolve_device_paths(self) -> list[Path]:
        """Expand device_access glob patterns to existing device files.

        Patterns that match nothing on the current platform (e.g. NVIDIA
        device nodes on WSL2, or /dev/dxg on bare Linux) are skipped, so the
        same policy file works unmodified on both.

        Returns:
            Resolved, deduplicated paths of device files that actually exist.
        """
        resolved = set()
        for pattern in self._device_access:
            resolved.update(Path(match).resolve() for match in glob.glob(pattern))
        return list(resolved)

    def apply(self):
        rod = list(filter(lambda p: p.is_dir(), self._read_only))
        rof = list(filter(lambda p: not p.is_dir(), self._read_only))
        rwd = list(filter(lambda p: p.is_dir(), self._read_write))
        rwf = list(filter(lambda p: not p.is_dir(), self._read_write))
        devices = self._resolve_device_paths()

        strict = self._compatibility == LandLockCompatibility.HARD_REQUIREMENT
        sandbox = Landlock(strict=strict) \
            .allow_all_scope() \
            .allow_all_network() \
            .add_path_rule('/', access=AccessFs.EXECUTE) \
            .add_path_rule(*rwd, access=FileSystemPolicy.READ_WRITE_DIR_ACCESS) \
            .add_path_rule(*rwf, access=FileSystemPolicy.READ_WRITE_FILE_ACCESS) \
            .add_path_rule(*rod, access=FileSystemPolicy.READ_ONLY_DIR_ACCESS) \
            .add_path_rule(*rof, access=FileSystemPolicy.READ_ONLY_FILE_ACCESS)

        if devices:
            sandbox.add_path_rule(*devices, access=FileSystemPolicy.DEVICE_ACCESS)

        sandbox.apply()

        logger.info("Policy applied")
