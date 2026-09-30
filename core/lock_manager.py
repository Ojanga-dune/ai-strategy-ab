import os
import sys
import logging

def acquire_lock(lock_file: str):
    """
    Ensures only one instance of the bot is running.
    Creates a .lock file containing the current process PID.
    """
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r') as f:
                pid = int(f.read().strip())

            # Check if the process with that PID is actually running
            import psutil
            if psutil.pid_exists(pid):
                return False, pid
        except (ValueError, OSError):
            # Lock file is corrupt or unreadable, assume it's stale
            pass

    # Create lock file with current PID
    try:
        with open(lock_file, 'w') as f:
            f.write(str(os.getpid()))
        return True, os.getpid()
    except OSError as e:
        return False, None

def release_lock(lock_file: str):
    """Removes the lock file upon clean exit."""
    try:
        if os.path.exists(lock_file):
            os.remove(lock_file)
    except OSError:
        pass
