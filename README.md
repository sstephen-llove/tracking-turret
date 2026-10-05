# Project Rias

Rias is an interactive robotic turret that combines computer vision, voice interaction, and AI-driven personality. Built with Python, Arduino, and custom mechanical hardware, it tracks visual subjects and responds to spoken input through physical gestures. A small OLED display gives the robot a cute face.

## About the Project

I’m building Rias to explore how mechanical design, embedded programming, and computer vision work together in an expressive robot.

The mechanical platform uses a NEMA 17 stepper motor driving a ring gear through a pinion, with two mirrored servos controlling tilt. The computer handles vision and voice processing, while the Arduino executes motor movements.

Rias communicates through body language. It can nod in agreement, shake its head in refusal, wiggle with excitement, or droop in sadness.

## Features

### Computer Vision

Three selectable tracking modes are implemented:

- **Ball tracking** using HSV color filtering and contour detection.
- **Face tracking** using MediaPipe face detection.
- **Hand tracking** using MediaPipe hand landmarks.

The main application displays camera footage with detection overlays, frame rate, tracking errors, and behavior status. It coordinates idle, searching, tracking, and expressive gesture states.

### Voice Interaction and Personality

Rias uses speech recognition and the Gemini API to interpret spoken input and select a response.

1. A microphone captures speech.
2. Google speech recognition converts the audio to text.
3. Recognized phrases containing a configured activation word are sent to Gemini with recent conversation history.
4. Gemini returns a predefined action tag.
5. Python translates that tag into a behavior state for the Arduino.
6. The Arduino performs the corresponding movement.

Gemini selects predefined actions rather than generating executable code. The personality prompt encourages playful, opinionated responses, including occasional refusal.

The current implementation responds through movement, without synthesized speech.

### Expressive Behaviors

| Behavior | Physical response |
|---|---|
| Agreement | Vertical nod |
| Refusal | Horizontal head shake |
| Excitement | Fast wiggle with an upward tilt |
| Sadness | Downward droop |
| Anger | Rapid alternating pan and tilt movements |
| Searching | Continuous pan movement |
| Idle | Stops pan movement and returns tilt to neutral |

### Embedded Control

The Arduino firmware provides:

- Stepper-based pan control.
- Coordinated movement of two mirrored tilt servos.
- Tracking dead zones to reduce movement near the image center.
- Predefined gesture routines.
- A communication timeout that requests a stepper stop and centers the tilt servos after 500 milliseconds without a complete packet.

## System Architecture

The software has three main responsibilities:

| Component | Responsibility |
|---|---|
| Camera bridge | Captures frames and makes them available through shared memory |
| Python application | Processes vision, interprets voice input, requests Gemini responses, and selects behavior states |
| Arduino firmware | Receives tracking errors and behavior states, then controls the motors |

Voice recognition runs in a background thread alongside the main vision loop.

The OLED serves as the robot’s visual face. Its display logic is not included in the files documented here.

## Repository Files

| File | Description |
|---|---|
| `cam_bridge_32(1).py` | Camera bridge intended for the PS3 Eye setup. Captures frames through Windows DirectShow and writes them to named shared memory. |
| `turret_tracker(1).py` | Main application with computer vision, voice recognition, Gemini integration, behavior management, and Arduino communication. |
| `turret_tracker_webcam(1).py` | Standalone webcam tracking variant with direct camera capture and no Gemini voice integration. |
| `arduino_auto_track_ps3(1).ino` | Arduino firmware for pan, mirrored tilt servos, tracking, searching, and expressive gestures. |

## Hardware

### Core Components

| Component | Specification |
|---|---|
| Microcontroller | Arduino-compatible UNO R3, ATmega328P |
| Pan motor | STEPPERONLINE NEMA 17, 2 A, 59 N·cm |
| Stepper driver | BIGTREETECH TMC2209 V1.3 |
| Standard servos | MG996R metal-gear servos |
| Micro servos | SG90 servos |
| Display | 1.3-inch I²C OLED, 128 × 64 pixels |
| Voice input | USB microphone |
| Camera input | PS3 Eye through the camera bridge, or a webcam through the standalone variant |
| Mechanical assembly | Custom ring gear, pinion, printed components, M3 screws, and heat-set inserts |

Additional purchased components include a 4S LiPo battery, adjustable power supply, step-down converters, brushless ESCs, laser modules, and prototyping supplies. Their purchase does not imply that control support is implemented in these scripts.

## Software Dependencies

### Python

The scripts use:

- `opencv-python`
- `mediapipe`
- `numpy`
- `pyserial`
- `requests`
- `SpeechRecognition`
- A microphone backend compatible with `SpeechRecognition`, typically PyAudio

The code uses the `mp.solutions` MediaPipe interface. A compatible environment is required; tested dependency versions have not yet been documented.

### Arduino

The firmware requires:

- `FastAccelStepper`
- `ServoTimer2Plus`

## Configuration

The current scripts are configured for a Windows development environment.

Before running, review:

- **Serial port:** currently `COM4`.
- **Serial baud rate:** `500000` in both the Python application and Arduino firmware.
- **Camera selection:** the bridge checks camera indices `1`, `0`, and `2`; the webcam variant uses index `0`.
- **Microphone selection:** the voice listener uses the default microphone.
- **Gemini configuration:** the API key is blank, and the configured model endpoint must be checked against the models available to your account.

Keep API credentials out of the public repository.

### Project Naming

Some code strings and the personality prompt still refer to the robot as **Terry**. The current voice activation check recognizes **“terry”** or **“turret.”** Saying **“Rias”** alone does not currently activate an API request.

## Running the Main Application

These steps describe the intended startup sequence. A complete, tested environment setup is still being documented.

1. Install the required Arduino libraries and upload the firmware using Arduino IDE. If prompted, allow the IDE to place the sketch in a matching folder.
2. Configure the Python environment, serial port, microphone, and Gemini access.
3. Start the camera bridge.
4. Keep the bridge running and start the main tracker in a second terminal.

Using the current filenames:

```bash
python "cam_bridge_32(1).py"
```

In a separate terminal:

```bash
python "turret_tracker(1).py"
```

If the PS3 Eye driver requires a separate 32-bit Python environment, run the bridge with that interpreter and the tracker with its compatible environment.

The main tracker starts in **idle** mode. If it cannot connect to the Arduino, it continues in vision-only mode.

## Keyboard Controls

### Main Tracker

| Key | Action |
|---|---|
| `1` | Select ball tracking |
| `2` | Select face tracking |
| `3` | Select hand tracking |
| `S` | Start searching |
| `Space` | Set idle behavior |
| `Q` | Quit |

An active timed gesture can finish before idle behavior takes effect. These keyboard controls are not a hardware emergency stop.

### Standalone Webcam Variant

| Key | Action |
|---|---|
| `1` | Select ball tracking |
| `2` | Select face tracking |
| `3` | Select hand tracking |
| `N` | Request a head shake |
| `Q` | Quit |

## Compatibility Notes

The included Arduino firmware expects horizontal and vertical **tracking errors**, matching the main `turret_tracker(1).py` application.

The standalone webcam variant instead sends a calculated **tilt angle** in the vertical field. It is not interchangeable with the main tracker when using this firmware.

The camera bridge and main tracker rely on Windows named shared memory, and both camera capture scripts use Windows DirectShow.

## Development Status

Rias is an ongoing hardware and software project. The uploaded source implements the host-side vision and voice pipeline, serial communication, and Arduino movement routines. End-to-end operation depends on the local hardware, firmware libraries, Python environment, and API configuration.

Next steps include:

- Updating remaining Terry references to Rias.
- Adding OLED face-rendering code.
- Documenting tested dependency versions.
- Moving local settings and credentials into external configuration.
- Adding wiring documentation and assembly photos.
- Publishing demonstration videos and measured performance results.

## Author

**Stephen Love**  
Mechanical Engineering student at the University of Georgia
