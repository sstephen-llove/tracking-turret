import cv2
import time
import serial
import struct
import numpy as np
import mediapipe as mp

WIDTH, HEIGHT = 640, 480
V_FOV_DEGREES = 43.0  
CENTER_X, CENTER_Y = WIDTH // 2, HEIGHT // 2

try:
    arduino = serial.Serial('COM4', 500000, timeout=0.05)
    print("SUCCESS: Connected to Arduino on COM4 at 500,000 Baud")
    serial_active = True
except:
    print("WARNING: Arduino not found on COM4. Running in Vision-Only mode.")
    serial_active = False

mp_face = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5)
mp_hands = mp.solutions.hands.Hands(max_num_hands=1, model_complexity=0, min_detection_confidence=0.5)

class AdaptiveSmoother:
    def __init__(self):
        self.sx = float(CENTER_X)
        self.sy = float(CENTER_Y)
        self.initialized = False

    def update(self, x, y):
        if not self.initialized:
            self.sx, self.sy = float(x), float(y)
            self.initialized = True
            return int(self.sx), int(self.sy)

        dist = np.hypot(x - self.sx, y - self.sy)
        if dist < 1.5:
            return int(self.sx), int(self.sy)

        alpha = 1.0 
        self.sx = alpha * x + (1.0 - alpha) * self.sx
        self.sy = alpha * y + (1.0 - alpha) * self.sy
        return int(self.sx), int(self.sy)

    def reset(self):
        self.initialized = False

smoother = AdaptiveSmoother()

def get_zoom_crop(frame, center_pt, crop_w=320, crop_h=240):
    tx, ty = center_pt
    x1 = int(np.clip(tx - crop_w // 2, 0, WIDTH - crop_w))
    y1 = int(np.clip(ty - crop_h // 2, 0, HEIGHT - crop_h))
    crop = frame[y1 : y1 + crop_h, x1 : x1 + crop_w]
    zoomed = cv2.resize(crop, (WIDTH, HEIGHT), interpolation=cv2.INTER_LINEAR)
    return zoomed, x1, y1, crop_w / WIDTH, crop_h / HEIGHT

mode = 2  
MODE_NAMES = {1: "1: BALL", 2: "2: FACE (2X ZOOM)", 3: "3: HAND (2X ZOOM)"}

ai_roi_center = None
ai_small_target = False
shake_until = 0

lower_color = np.array([20, 100, 100])
upper_color = np.array([40, 255, 255])

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FPS, 30)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)      
cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

print("\n--- TRACKER ACTIVE (BINARY MODE) ---")

arduino_packet_struct = struct.Struct('<BBhhB')

prev_time = time.time()
fps = 0.0

while True:
    ret, frame = cap.read()
    if not ret: break
    
    frame = cv2.flip(frame, 1)
    target_found = False
    raw_cx, raw_cy = CENTER_X, CENTER_Y
    current_target_width = 0

    if mode == 1:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower_color, upper_color)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest) > 500:
                x, y, w, h = cv2.boundingRect(largest)
                raw_cx = x + w // 2; raw_cy = y + h // 2
                current_target_width = w
                target_found = True
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 255), 2)

    elif mode == 2:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        used_zoom = False

        if ai_roi_center is not None and ai_small_target:
            zoom_rgb, ox, oy, sx, sy = get_zoom_crop(rgb_frame, ai_roi_center)
            results = mp_face.process(zoom_rgb)
            if results.detections: used_zoom = True
        else:
            results = mp_face.process(rgb_frame)

        if results.detections:
            best_face = max(results.detections, key=lambda d: d.location_data.relative_bounding_box.width * d.location_data.relative_bounding_box.height)
            bbox = best_face.location_data.relative_bounding_box

            if used_zoom:
                fx = int(ox + (bbox.xmin * WIDTH) * sx)
                fy = int(oy + (bbox.ymin * HEIGHT) * sy)
                fw = int((bbox.width * WIDTH) * sx)
                fh = int((bbox.height * HEIGHT) * sy)
                cv2.rectangle(frame, (ox, oy), (ox + 320, oy + 240), (255, 255, 0), 1)
            else:
                fx = max(0, int(bbox.xmin * WIDTH))
                fy = max(0, int(bbox.ymin * HEIGHT))
                fw = int(bbox.width * WIDTH)
                fh = int(bbox.height * HEIGHT)

            raw_cx = fx + fw // 2
            raw_cy = fy + fh // 3
            current_target_width = fw
            
            ai_roi_center = (raw_cx, raw_cy)
            ai_small_target = fw < 110
            target_found = True
            cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), (255, 140, 0), 2)
        else:
            ai_roi_center = None

    elif mode == 3:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        used_zoom = False

        if ai_roi_center is not None and ai_small_target:
            zoom_rgb, ox, oy, sx, sy = get_zoom_crop(rgb_frame, ai_roi_center)
            results = mp_hands.process(zoom_rgb)
            if results.multi_hand_landmarks: used_zoom = True
        else:
            results = mp_hands.process(rgb_frame)

        if results.multi_hand_landmarks:
            hand_lms = results.multi_hand_landmarks[0]
            xs = [lm.x for lm in hand_lms.landmark]
            
            if used_zoom:
                palm_lm = hand_lms.landmark[9]
                raw_cx = int(ox + (palm_lm.x * WIDTH) * sx)
                raw_cy = int(oy + (palm_lm.y * HEIGHT) * sy)
                hand_span = (max(xs) - min(xs)) * WIDTH * sx
                cv2.rectangle(frame, (ox, oy), (ox + 320, oy + 240), (255, 255, 0), 1)
            else:
                mp_hands.solutions_drawing_utils = mp.solutions.drawing_utils
                mp_hands.solutions_drawing_utils.draw_landmarks(frame, hand_lms, mp.solutions.hands.HAND_CONNECTIONS)
                palm_lm = hand_lms.landmark[9]
                raw_cx = int(palm_lm.x * WIDTH)
                raw_cy = int(palm_lm.y * HEIGHT)
                hand_span = (max(xs) - min(xs)) * WIDTH

            current_target_width = hand_span
            ai_roi_center = (raw_cx, raw_cy)
            ai_small_target = hand_span < 120
            target_found = True
            cv2.circle(frame, (raw_cx, raw_cy), 10, (255, 0, 255), -1)
        else:
            ai_roi_center = None

    error_x = 0
    tilt_deg = 90
    locked_state = 0

    cv2.drawMarker(frame, (CENTER_X, CENTER_Y), (255, 255, 255), cv2.MARKER_CROSS, 20, 1)

    if target_found:
        cx, cy = smoother.update(raw_cx, raw_cy)
        error_x = int(cx - CENTER_X)
        error_y = int(cy - CENTER_Y)
        
        base_tilt = 90 - (error_y / HEIGHT) * (V_FOV_DEGREES * 2.5)
        
        # --- CRANKED DYNAMIC PARALLAX COMPENSATION ---
        if mode == 2 and current_target_width > 0:
            # Shifted to [25, 80] to force a massive upward tilt when close (large face width)
            dynamic_offset = np.interp(current_target_width, [40, 150], [25, 95])
        else:
            dynamic_offset = 30 
            
        tilt_deg = int(base_tilt + dynamic_offset)
        
        locked_state = 1
        cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)
        cv2.line(frame, (CENTER_X, CENTER_Y), (cx, cy), (0, 255, 255), 2)
    else:
        smoother.reset()
    
    if time.time() < shake_until:
        locked_state = 2
        cv2.putText(frame, "SHAKING HEAD!", (WIDTH//2 - 100, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 165, 255), 3)

    if serial_active:
        arduino.reset_output_buffer()
        packet = arduino_packet_struct.pack(0xAA, 0x55, error_x, tilt_deg, locked_state)
        arduino.write(packet)

    curr_time = time.time()
    dt = curr_time - prev_time
    if dt > 0: fps = 0.9 * fps + 0.1 * (1.0 / dt)
    prev_time = curr_time

    status_str = "LOCKED" if locked_state == 1 else ("SHAKING" if locked_state == 2 else "SEARCHING")
    color = (0, 255, 0) if locked_state == 1 else ((0, 165, 255) if locked_state == 2 else (0, 0, 255))
    
    cv2.putText(frame, f"FPS: {int(fps)} | {MODE_NAMES[mode]} | Offset: {int(dynamic_offset) if target_found else 0}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 255), 2)
    cv2.putText(frame, f"{status_str} | Pan: {error_x} | Tilt: {tilt_deg}", (10, HEIGHT - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    cv2.imshow("Turret Vision Tracker", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('1'): mode = 1; smoother.reset()
    elif key == ord('2'): mode = 2; smoother.reset(); ai_roi_center = None
    elif key == ord('3'): mode = 3; smoother.reset(); ai_roi_center = None
    elif key == ord('n'): shake_until = time.time() + 1.5
    elif key == ord('q'): break

cap.release()
cv2.destroyAllWindows()
if serial_active: arduino.close()