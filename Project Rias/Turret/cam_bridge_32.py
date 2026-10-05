import mmap
import struct
import time
import cv2

WIDTH, HEIGHT = 640, 480
FRAME_BYTES = WIDTH * HEIGHT * 3
SHM_SIZE = FRAME_BYTES + 4

def open_ps3_eye():
    """Scans camera indexes 1, 0, and 2 to find the working PS3 Eye."""
    for idx in [1, 0, 2]:
        print(f"Testing Camera Index {idx}...")
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if cap.isOpened():
            # OPTIMIZATION: Force driver buffer to 1 frame to prevent internal queue latency
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, 60)
            ret, frame = cap.read()
            if ret and frame is not None:
                print(f"SUCCESS: Locked onto camera at Index {idx}!")
                return cap, idx
        cap.release()
    return None, -1

cap, active_idx = open_ps3_eye()
if cap is None:
    print("ERROR: Could not open any camera! Unplug and replug the PS3 Eye USB.")
    exit(1)

shm = mmap.mmap(-1, SHM_SIZE, tagname="PS3EyeStream")
print(f"Streaming Index {active_idx} (640x480 @ 60 FPS) to shared RAM...")
print("Now run: py -3-64 turret_tracker.py in your second terminal.")

# OPTIMIZATION: Pre-compile struct to save CPU cycles in the while loop
frame_id_struct = struct.Struct("I")

frame_id = 0
prev_t = time.time()
fps = 0.0

try:
    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            print("Frame drop detected — reconnecting camera...")
            cap.release()
            time.sleep(1.0)
            cap, active_idx = open_ps3_eye()
            continue

        if frame.shape[1] != WIDTH or frame.shape[0] != HEIGHT:
            frame = cv2.resize(frame, (WIDTH, HEIGHT))

        frame_id = (frame_id + 1) % 2_000_000_000
        shm.seek(0)
        shm.write(frame_id_struct.pack(frame_id))
        shm.write(frame.tobytes())

        now = time.time()
        dt = now - prev_t
        prev_t = now
        if dt > 0:
            fps = 0.95 * fps + 0.05 * (1.0 / dt)
        if frame_id % 60 == 0:
            print(f"Bridge Active | Cam Index: {active_idx} | Frame: {frame_id} | {int(fps)} FPS", end="\r")

except KeyboardInterrupt:
    print("\nStopping bridge...")
finally:
    if cap is not None:
        cap.release()
    shm.close()