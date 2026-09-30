import os
import time
import subprocess
import sys
from core.lock_manager import acquire_lock, release_lock

def test_single_instance():
    lock_file = "test_bot.lock"

    # Clean start
    if os.path.exists(lock_file):
        os.remove(lock_file)

    print("Testing first instance...")
    success1, pid1 = acquire_lock(lock_file)
    print(f"Instance 1 acquired lock: {success1} (PID: {pid1})")

    if not success1:
        print("FAILED: First instance should have acquired lock")
        return

    print("\nTesting second instance (should fail)...")
    success2, pid2 = acquire_lock(lock_file)
    print(f"Instance 2 acquired lock: {success2} (PID: {pid2})")

    if success2:
        print("FAILED: Second instance should NOT have acquired lock")
    else:
        print("SUCCESS: Second instance blocked as expected")

    print("\nReleasing lock...")
    release_lock(lock_file)

    print("\nTesting third instance after release...")
    success3, pid3 = acquire_lock(lock_file)
    print(f"Instance 3 acquired lock: {success3} (PID: {pid3})")

    if not success3:
        print("FAILED: Third instance should have acquired lock after release")
    else:
        print("SUCCESS: Lock released and re-acquired correctly")

    release_lock(lock_file)

if __name__ == "__main__":
    try:
        test_single_instance()
    except Exception as e:
        print(f"Test errored: {e}")
