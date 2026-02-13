
import os
import psutil
import sys
import time
from typing import List, Tuple

def check_and_cleanup_zombies(auto_kill: bool = False, current_pid: int = None) -> List[int]:
    """
    Check for other running instances of lethologic_anomia.py and offer to kill them.
    
    Args:
        auto_kill: If True, automatically kill zombie processes without prompting.
        current_pid: The PID of the current process (to avoid killing self).
                     Defaults to os.getpid() if not provided.
                     
    Returns:
        List of killed process IDs.
    """
    if current_pid is None:
        current_pid = os.getpid()
        
    zombies = []
    killed_pids = []
    
    # Iterate through all running processes
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # Check if process is not self
            if proc.info['pid'] == current_pid:
                continue
                
            # Check for python processes running something with "lethologic" in the name
            cmdline = proc.info['cmdline']
            if cmdline and len(cmdline) > 1:
                # Look for python execution
                if 'python' in proc.info['name'].lower() or 'python' in cmdline[0].lower():
                    # Check arguments for our script name
                    # Matches "lethologic_anomia.py" or just "lethologic_anomia"
                    is_target = False
                    for arg in cmdline:
                        if 'lethologic_anomia' in arg and not arg.endswith('.sh'):
                            is_target = True
                            break
                    
                    if is_target:
                        zombies.append(proc)
                        
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
            
    if not zombies:
        return []
        
    print(f"\n⚠️  Found {len(zombies)} other instance(s) of Lethologic Anomia running:")
    for z in zombies:
        try:
            print(f"  - PID {z.info['pid']}: {' '.join(z.info['cmdline'])}")
            # Get memory usage if possible
            mem_info = z.memory_info()
            print(f"    Memory: {mem_info.rss / (1024*1024):.2f} MB")
        except:
            print(f"  - PID {z.info['pid']} (details unavailable)")

    if auto_kill:
        print("\nUsing --force-cleanup, terminating zombie processes...")
        should_kill = True
    else:
        # Prompt user
        response = input("\nDo you want to terminate these processes? [y/N]: ").strip().lower()
        should_kill = response in ('y', 'yes')
        
    if should_kill:
        for z in zombies:
            try:
                pid = z.info['pid']
                print(f"Killing PID {pid}...", end=" ")
                z.terminate()
                z.wait(timeout=3)
                print("Terminated.")
                killed_pids.append(pid)
            except psutil.TimeoutExpired:
                print("Timed out, forcing kill...", end=" ")
                try:
                    z.kill()
                    print("Killed.")
                    killed_pids.append(pid)
                except Exception as e:
                    print(f"Failed: {e}")
            except Exception as e:
                print(f"Error: {e}")
    else:
        print("Ignoring zombie processes (this may cause OOM errors).")
        
    return killed_pids
