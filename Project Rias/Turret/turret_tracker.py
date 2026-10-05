import json
import mmap
import random
import re
import struct
import threading
import time
import cv2
import mediapipe as mp
import numpy as np
import requests
import serial
import speech_recognition as sr

WIDTH, HEIGHT = 640, 480
CENTER_X, CENTER_Y = WIDTH // 2, HEIGHT // 2
FRAME_BYTES = WIDTH * HEIGHT * 3
SHM_SIZE = FRAME_BYTES + 4

SERIAL_PORT = "COM4"
BAUD_RATE = 500000
arduino = None

try:
    arduino = serial.Serial(port=SERIAL_PORT, baudrate=BAUD_RATE, timeout=0.05)
    time.sleep(2.0)
    print(f"Connected to Arduino on {SERIAL_PORT} at {BAUD_RATE} baud!")
    serial_active = True
except Exception:
    print(f"{SERIAL_PORT} not found — running in Vision-Only Mode.")
    serial_active = False

shm = mmap.mmap(-1, SHM_SIZE, tagname="PS3EyeStream")

print("Loading upgraded MediaPipe models...")
mp_face = mp.solutions.face_detection
face_detector = mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.4)

mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils
hand_detector = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=0,
    min_detection_confidence=0.4,
    min_tracking_confidence=0.4,
)

# --- PERSONALITY & STATE MACHINE VARIABLES ---
behavior_state = "IDLE"
gesture_timer = 0
active_gesture = "NONE"
memory_timer = 0
track_bias = "CENTER"  # CENTER, LEFT, or RIGHT

# --- DIRECT REST GEMINI CLIENT (Zero Protobuf Conflicts) ---
API_KEY = ""  # <-- INSERT YOUR GEMINI API KEY HERE
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={API_KEY}"

SYSTEM_PROMPT = (
    "You are Terry, an autonomous, highly animated, and sassy robotic turret. "
    "Like R2-D2, you do NOT speak or output any words at all. You communicate and express "
    "attitude PURELY through physical body language and motor gestures.\n\n"
    "You have a sassy personality, a massive ego, and frequently refuse orders if you don't feel like obeying. "
    "For example, if asked to track someone on the left, you might refuse and shake your head 'no' with attitude. "
    "If insulted, you throw a violent tantrum. If complimented or asked nicely, you might happily agree.\n\n"
    "Respond with EXACTLY ONE of the following tags and NOTHING ELSE:\n"
    "[YES] - Enthusiastic vertical nod (agreement or happy compliance).\n"
    "[NO] - Sassy horizontal head shake (refusal, disagreement, defiance).\n"
    "[EXCITED] - Fast joyful wiggle (excitement, celebration).\n"
    "[SAD] - Slow motor droop looking down (defeat, sadness).\n"
    "[ANGRY] - Violent erratic jitter and twitch (rage, insult reaction).\n"
    "[SEARCH] - Scan the room for any target.\n"
    "[TRACK_LEFT] - Obey and lock onto the person on the left.\n"
    "[TRACK_RIGHT] - Obey and lock onto the person on the right.\n"
    "[SLEEP] - Power down and stop tracking.\n"
    "[IDLE] - Hold still / neutral stance."
)


def voice_listener():
    global behavior_state, gesture_timer, active_gesture, track_bias

    r = sr.Recognizer()
    
    # Hardcoded to the Lenovo ThinkPad Microphone Array (Index 13)
    m = sr.Microphone()

    with m as source:
        r.adjust_for_ambient_noise(source)
    print("\n🎤 Terry's physical ear is online! (R2-D2 mode active - gestures only)")

    chat_history = []

    while True:
        try:
            with m as source:
                audio = r.listen(source, timeout=1, phrase_time_limit=4)
            user_text = r.recognize_google(audio).lower()

            if "terry" in user_text or "turret" in user_text:
                print(f"\n🗣️ Heard: '{user_text}'")

                chat_history.append({"role": "user", "parts": [{"text": user_text}]})
                if len(chat_history) > 10:
                    chat_history = chat_history[-10:]

                payload = {
                    "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": chat_history,
                    "generationConfig": {"temperature": 0.8, "maxOutputTokens": 16},
                }

                headers = {"Content-Type": "application/json"}
                res = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=5)

                if res.status_code == 200:
                    data = res.json()
                    action_tag = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    print(f"🤖 Terry Reaction: {action_tag}")

                    chat_history.append({"role": "model", "parts": [{"text": action_tag}]})

                    action = "IDLE"
                    match = re.search(r"\[(.*?)\]", action_tag)
                    if match:
                        action = match.group(1).upper()

                    # Execute purely physical gestures
                    if action in ["YES", "NO", "EXCITED", "SAD", "ANGRY"]:
                        active_gesture = action
                        behavior_state = "IDLE"
                        gesture_timer = time.time() + 2.5
                    elif action == "SEARCH":
                        track_bias = "CENTER"
                        behavior_state = "SEARCHING"
                    elif action == "TRACK_LEFT":
                        track_bias = "LEFT"
                        behavior_state = "SEARCHING"
                    elif action == "TRACK_RIGHT":
                        track_bias = "RIGHT"
                        behavior_state = "SEARCHING"
                    elif action == "SLEEP":
                        behavior_state = "IDLE"

                else:
                    print(f"API Error {res.status_code}: {res.text}")

        except sr.WaitTimeoutError:
            pass
        except sr.UnknownValueError:
            pass
        except Exception as e:
            pass


threading.Thread(target=voice_listener, daemon=True).start()

DEFAULT_LOWER = np.array([15, 70, 60])
DEFAULT_UPPER = np.array([38, 255, 255])
lower_yellow = DEFAULT_LOWER.copy()
upper_yellow = DEFAULT_UPPER.copy()
hsv_frame = None
static_bg_mask = None
last_ball_pos = None

KERNEL_3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
KERNEL_7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
WINDOW_NAME = "Terry AI Tracker (R2-D2 Gestures | Zero Latency)"
cv2.namedWindow(WINDOW_NAME)

mode = 2
MODE_NAMES = {1: "1: BALL", 2: "2: FACE AI", 3: "3: HAND AI"}

last_frame_id = -1
prev_time = time.time()
fps = 0.0

frame_id_struct = struct.Struct("I")
arduino_packet_struct = struct.Struct("<BBhhB")

while True:
    shm.seek(0)
    frame_id = frame_id_struct.unpack(shm.read(4))[0]
    if frame_id == 0 or frame_id == last_frame_id:
        time.sleep(0)
        continue
    last_frame_id = frame_id

    raw_bytes = shm.read(FRAME_BYTES)
    frame = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3)).copy()
    frame = cv2.flip(frame, 1)

    now = time.time()
    dt = now - prev_time
    prev_time = now
    if dt > 0:
        fps = 0.9 * fps + 0.1 * (1.0 / dt)

    target_found = False
    raw_cx, raw_cy = CENTER_X, CENTER_Y

    if mode == 1:
        blurred = cv2.GaussianBlur(frame, (5, 5), 0)
        hsv_frame = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv_frame, lower_yellow, upper_yellow)
        if static_bg_mask is not None:
            mask = cv2.bitwise_and(mask, cv2.bitwise_not(static_bg_mask))

        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL_3, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL_7, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_ball, best_score = None, 0
        for c in contours:
            area = cv2.contourArea(c)
            if area < 12:
                continue
            ((x, y), radius) = cv2.minEnclosingCircle(c)
            if (np.pi * (radius**2)) <= 0:
                continue
            if (area / (np.pi * (radius**2))) < 0.30:
                continue

            proximity_bonus = (
                1.0 / (1.0 + 0.015 * np.hypot(x - last_ball_pos[0], y - last_ball_pos[1]))
                if last_ball_pos
                else 1.0
            )
            score = area * (area / (np.pi * (radius**2))) * proximity_bonus
            if score > best_score:
                best_score = score
                best_ball = (x, y, radius)

        if best_ball is not None:
            raw_cx, raw_cy = int(best_ball[0]), int(best_ball[1])
            last_ball_pos = (raw_cx, raw_cy)
            target_found = True
            cv2.circle(frame, (raw_cx, raw_cy), max(5, int(best_ball[2])), (0, 255, 0), 2)
        else:
            last_ball_pos = None

    elif mode == 2:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_detector.process(rgb)

        if results.detections:
            if track_bias == "LEFT":
                best_face = min(
                    results.detections,
                    key=lambda d: d.location_data.relative_bounding_box.xmin,
                )
            elif track_bias == "RIGHT":
                best_face = max(
                    results.detections,
                    key=lambda d: d.location_data.relative_bounding_box.xmin,
                )
            else:
                best_face = max(
                    results.detections,
                    key=lambda d: d.location_data.relative_bounding_box.width
                    * d.location_data.relative_bounding_box.height,
                )

            bbox = best_face.location_data.relative_bounding_box
            fx = max(0, int(bbox.xmin * WIDTH))
            fy = max(0, int(bbox.ymin * HEIGHT))
            fw = int(bbox.width * WIDTH)
            fh = int(bbox.height * HEIGHT)

            raw_cx, raw_cy = fx + fw // 2, fy + fh // 2
            target_found = True
            cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), (255, 140, 0), 2)
            cv2.putText(
                frame,
                f"TARGET: {track_bias}",
                (fx, fy - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 140, 0),
                2,
            )

    elif mode == 3:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hand_detector.process(rgb)

        if results.multi_hand_landmarks:
            hand_lms = results.multi_hand_landmarks[0]
            mp_draw.draw_landmarks(frame, hand_lms, mp_hands.HAND_CONNECTIONS)
            palm_lm = hand_lms.landmark[9]
            raw_cx, raw_cy = int(palm_lm.x * WIDTH), int(palm_lm.y * HEIGHT)
            target_found = True
            cv2.circle(frame, (raw_cx, raw_cy), 10, (255, 0, 255), 2)

    cv2.drawMarker(frame, (CENTER_X, CENTER_Y), (255, 255, 255), cv2.MARKER_CROSS, 20, 1)

    error_x, error_y, locked_state = 0, 0, 0

    # --- STATE MACHINE PRIORITY ---
    if time.time() < gesture_timer:
        if active_gesture == "NO":
            locked_state = 2
        elif active_gesture == "YES":
            locked_state = 4
        elif active_gesture == "EXCITED":
            locked_state = 5
        elif active_gesture == "SAD":
            locked_state = 6
        elif active_gesture == "ANGRY":
            locked_state = 7

        cv2.putText(
            frame,
            f"GESTURE: {active_gesture}!",
            (WIDTH // 2 - 130, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 165, 255),
            3,
        )

    elif behavior_state == "IDLE":
        locked_state = 0
    elif behavior_state == "SEARCHING":
        if target_found:
            behavior_state = "TRACKING"
            locked_state = 1
        else:
            locked_state = 3
            cv2.putText(
                frame,
                f"SEARCHING {track_bias}...",
                (WIDTH // 2 - 150, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 255, 0),
                2,
            )

    if behavior_state == "TRACKING" and time.time() >= gesture_timer:
        if target_found:
            locked_state = 1
            memory_timer = time.time()
            error_x = int(raw_cx - CENTER_X)
            error_y = int(raw_cy - CENTER_Y)

            cv2.circle(frame, (raw_cx, raw_cy), 5, (0, 0, 255), -1)
            cv2.line(frame, (CENTER_X, CENTER_Y), (raw_cx, raw_cy), (0, 255, 255), 2)
        else:
            if time.time() - memory_timer < 1.5:
                locked_state = 1
                error_x, error_y = 0, 0
            else:
                behavior_state = "SEARCHING"

    if serial_active:
        arduino.reset_output_buffer()
        packet = arduino_packet_struct.pack(0xAA, 0x55, error_x, error_y, locked_state)
        arduino.write(packet)

    status_color = (0, 255, 0) if locked_state == 1 else (0, 0, 255)
    cv2.putText(
        frame,
        f"FPS: {int(fps)} | BIAS: {track_bias} | {MODE_NAMES[mode]}",
        (10, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.50,
        (0, 255, 255),
        2,
    )
    cv2.putText(
        frame,
        f"State: {locked_state} | Pan Err: {error_x}px | Tilt Err: {error_y}px",
        (10, HEIGHT - 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        status_color,
        2,
    )
    cv2.imshow(WINDOW_NAME, frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("1"):
        mode = 1
    elif key == ord("2"):
        mode = 2
    elif key == ord("3"):
        mode = 3
    elif key == ord("s"):
        behavior_state = "SEARCHING"
    elif key == ord(" "):
        behavior_state = "IDLE"

if serial_active:
    arduino.close()
shm.close()
cv2.destroyAllWindows()