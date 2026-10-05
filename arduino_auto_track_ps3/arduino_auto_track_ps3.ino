#include "FastAccelStepper.h"
#include <ServoTimer2Plus.h>

#define EN_PIN          4
#define DIR_PIN         3
#define STEP_PIN        9  
#define LEFT_SERVO_PIN  5
#define RIGHT_SERVO_PIN 6

FastAccelStepperEngine engine = FastAccelStepperEngine();
FastAccelStepper *stepper = NULL;

ServoTimer2Plus leftTilt;
ServoTimer2Plus rightTilt;

int16_t panErrorX = 0;
int16_t tiltErrorY = 0;
uint8_t isLocked = 0;

float currentTilt = 90.0;
unsigned long lastPacketTime = 0;
bool newFrameReceived = false;

void setup() {
  Serial.begin(500000);
  
  pinMode(EN_PIN, OUTPUT);
  digitalWrite(EN_PIN, LOW); 

  leftTilt.attach(LEFT_SERVO_PIN);
  rightTilt.attach(RIGHT_SERVO_PIN);
  leftTilt.write(1500); 
  rightTilt.write(1500);

  engine.init();
  stepper = engine.stepperConnectToPin(STEP_PIN);
  
  if (stepper) {
    stepper->setDirectionPin(DIR_PIN);
    stepper->setAcceleration(60000); 
  }
}

void loop() {
  readBinaryData();

  if (millis() - lastPacketTime > 500) {
    if (stepper) stepper->stopMove();
    isLocked = 0;
    leftTilt.write(1500);
    rightTilt.write(1500);
    return;
  }

  if (stepper) {
    if (isLocked == 1) {
      // --- NORMAL TRACKING ---
      int deadzoneX = 8; 
      if (abs(panErrorX) > deadzoneX) {
        uint32_t currentSpeed = map(abs(panErrorX), deadzoneX, 320, 800, 22000);
        stepper->setSpeedInHz(currentSpeed);
        if (panErrorX > 0) stepper->runBackward(); 
        else stepper->runForward();
      } else {
        stepper->stopMove();
      }

      int deadzoneY = 8;
      if (newFrameReceived) {
        if (abs(tiltErrorY) > deadzoneY) {
          float moveAmount = (float)tiltErrorY * 0.015; 
          moveAmount = constrain(moveAmount, -2.5, 2.5);
          currentTilt -= moveAmount; 
          currentTilt = constrain(currentTilt, 10.0, 175.0);
        }
        newFrameReceived = false; 
      }
      
    } else if (isLocked == 2) {
      // STATE 2: NO (SHAKE HEAD)
      stepper->setSpeedInHz(10000); 
      stepper->moveTo(((millis() / 200) % 2 == 0) ? 600 : -600);
      currentTilt = 90.0;
      
    } else if (isLocked == 3) {
      // STATE 3: SEARCHING
      stepper->setSpeedInHz(2500); 
      stepper->runForward(); 
      currentTilt = 90.0;
      
    } else if (isLocked == 4) {
      // STATE 4: YES (NOD HEAD)
      stepper->stopMove(); 
      // Smooth sine wave nod (ranges from 60 to 120 degrees)
      currentTilt = 90.0 + 30.0 * sin(millis() / 150.0); 

    } else if (isLocked == 5) {
      // STATE 5: EXCITED (LOOK UP AND WIGGLE FAST)
      stepper->setSpeedInHz(15000); 
      stepper->moveTo(((millis() / 100) % 2 == 0) ? 300 : -300);
      currentTilt = 130.0; // Look up happily

    } else if (isLocked == 6) {
      // STATE 6: SAD (SLOWLY DROOP HEAD)
      stepper->stopMove();
      currentTilt -= 0.05; // Slowly drop head over time
      currentTilt = max(currentTilt, 20.0); // Don't snap the neck

    } else if (isLocked == 7) {
      // STATE 7: ANGRY (VIOLENT JITTER)
      stepper->setSpeedInHz(25000); 
      stepper->moveTo(((millis() / 50) % 2 == 0) ? 800 : -800);
      // Erratic jerky tilting
      currentTilt = 80.0 + 15.0 * sin(millis() / 30.0); 
      
    } else {
      // STATE 0: IDLE
      stepper->stopMove();
      currentTilt = 90.0;
    }

    // --- WRITE CURRENT TILT TO SERVOS ---
    int safeTilt = (int)currentTilt;
    int leftPulse = map(safeTilt, 0, 180, 2400, 600);
    int rightPulse = map(180 - safeTilt, 0, 180, 2400, 600); 
    leftTilt.write(leftPulse);
    rightTilt.write(rightPulse);
  }
}

void readBinaryData() {
  static uint8_t state = 0;
  static byte buf[5];
  static uint8_t idx = 0;

  while (Serial.available() > 0) {
    byte c = Serial.read();
    
    switch (state) {
      case 0: 
        if (c == 0xAA) state = 1; 
        break;
      case 1: 
        if (c == 0x55) { state = 2; idx = 0; } 
        else { state = 0; }
        break;
      case 2:
        buf[idx++] = c;
        if (idx == 5) {
          panErrorX  = (int16_t)(buf[0] | (buf[1] << 8));
          tiltErrorY = (int16_t)(buf[2] | (buf[3] << 8));
          isLocked   = buf[4];
          
          lastPacketTime = millis(); 
          newFrameReceived = true;
          state = 0;
        }
        break;
    }
  }
}