import os
import enum
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
                              AccessFs.TRUNCATE | AccessFs.IOCTL_DEV)

    def __init__(self):
        self._compatibility = LandLockCompatibility.BEST_EFFORT
        self._read_only = []
        self._read_write = []

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

    @staticmethod
    def _existing_paths(paths: list[Path]) -> list[Path]:
        """Drop policy paths that do not exist on a host machine.

        Landlock cannot add a rule for a missing path, and the policy lists
        platform-specific paths such as GPU device nodes that exist only on
        some host machines.

        Args:
            paths: Paths listed in the policy.

        Returns:
            Paths that exist on a host machine.
        """
        existing = [p for p in paths if p.exists()]
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            logger.info(f"Skipped missing policy paths: {missing}")
        return existing

    def apply(self):
        ro = self._existing_paths(self._read_only)
        rw = self._existing_paths(self._read_write)
        rod = list(filter(lambda p: p.is_dir(), ro))
        rof = list(filter(lambda p: not p.is_dir(), ro))
        rwd = list(filter(lambda p: p.is_dir(), rw))
        rwf = list(filter(lambda p: not p.is_dir(), rw))

        strict = self._compatibility == LandLockCompatibility.HARD_REQUIREMENT
        Landlock(strict=strict) \
            .allow_all_scope() \
            .allow_all_network() \
            .add_path_rule('/', access=AccessFs.EXECUTE) \
            .add_path_rule(*rwd, access=FileSystemPolicy.READ_WRITE_DIR_ACCESS) \
            .add_path_rule(*rwf, access=FileSystemPolicy.READ_WRITE_FILE_ACCESS) \
            .add_path_rule(*rod, access=FileSystemPolicy.READ_ONLY_DIR_ACCESS) \
            .add_path_rule(*rof, access=FileSystemPolicy.READ_ONLY_FILE_ACCESS) \
            .apply()

        logger.info("Policy applied")
