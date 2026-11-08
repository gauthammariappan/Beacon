/**
 * Beacon v2.1 · Raspberry Pi Pico 2W Firmware (Layer 1 Sensing & Motor Driver)
 * 
 * Hardware:
 *   - Microcontroller: Raspberry Pi Pico 2W (RP2350 / RP2040)
 *   - Microphones: 3x Small Sound Analog Mics (AO -> GP26, GP27, GP28)
 *   - Mic Power: GP2, GP3, GP4 set to HIGH (3.3V power rails, breadboardless)
 *   - Pan Servo: SG90 on GP15 (PWM)
 *   - Laser Turret: Red laser diode on GP13 via PN2222 transistor (1k base resistor)
 * 
 * Sampling & Signal Processing:
 *   - Sample rate: 16 kHz (62.5 us per round across all 3 mics)
 *   - Burst size: 256 samples per mic (16 ms capture window)
 *   - Target bands:
 *       * 2500 Hz (k=40) - Target Beep Alarm
 *       * 2000 Hz (k=32) - Low Reference Band
 *       * 3000 Hz (k=48) - High Reference Band
 *   - Rate: 50 Hz frame output (every 20 ms)
 * 
 * Protocol:
 *   - Telemetry -> Laptop:
 *       E,<ms>,L25,M25,R25,L20,M20,R20,L30,M30,R30
 *   - Commands <- Laptop:
 *       AIM,<pan>
 *       LASER,1 / LASER,0
 */

#include <Arduino.h>
#include <Servo.h>

// Pin Definitions
#define PIN_MIC_L_AO   26  // ADC0
#define PIN_MIC_M_AO   27  // ADC1
#define PIN_MIC_R_AO   28  // ADC2

#define PIN_MIC_L_VCC  2   // 3.3V Power Rail for Mic L
#define PIN_MIC_M_VCC  3   // 3.3V Power Rail for Mic M
#define PIN_MIC_R_VCC  4   // 3.3V Power Rail for Mic R

#define PIN_PAN_SERVO  15  // SG90 Pan Servo PWM
#define PIN_LASER_GATE 13  // PN2222 Base Gate (Active HIGH)

// Sampling constants
#define NUM_SAMPLES    256
#define SAMPLE_RATE    16000
#define SAMPLE_US      62.5  // 1 / 16000 s = 62.5 microseconds

// Goertzel Filter Bins for N=256, Fs=16000 Hz
// Resolution = Fs / N = 16000 / 256 = 62.5 Hz
// k = TargetFreq / 62.5
#define BIN_2000HZ     32  // 2000 / 62.5
#define BIN_2500HZ     40  // 2500 / 62.5
#define BIN_3000HZ     48  // 3000 / 62.5

// Precomputed Goertzel coefficients: 2.0 * cos(2.0 * PI * k / N)
static const float COEFF_2000 = 2.0f * cosf(2.0f * 3.1415926535f * 32.0f / 256.0f);
static const float COEFF_2500 = 2.0f * cosf(2.0f * 3.1415926535f * 40.0f / 256.0f);
static const float COEFF_3000 = 2.0f * cosf(2.0f * 3.1415926535f * 48.0f / 256.0f);

// Sample Buffers
int16_t samplesL[NUM_SAMPLES];
int16_t samplesM[NUM_SAMPLES];
int16_t samplesR[NUM_SAMPLES];

// Actuators
Servo panServo;
bool laserActive = false;
float currentPanAngle = 0.0f; // -45 deg to +45 deg

// Goertzel Energy Computation
float computeGoertzel(const int16_t* samples, int numSamples, float coeff) {
  float s_prev = 0.0f;
  float s_prev2 = 0.0f;

  for (int i = 0; i < numSamples; i++) {
    float s = (float)samples[i] + coeff * s_prev - s_prev2;
    s_prev2 = s_prev;
    s_prev = s;
  }

  // Power = s_prev^2 + s_prev2^2 - coeff * s_prev * s_prev2
  float power = (s_prev * s_prev) + (s_prev2 * s_prev2) - (coeff * s_prev * s_prev2);
  if (power < 0.0f) power = 0.0f;

  // Normalized magnitude relative to sample count
  return sqrtf(power) / (numSamples / 2.0f);
}

// Servo helper: map angle to servo degrees (0 to 180)
// Supports both absolute servo degrees (e.g. 20..180, where 90 is center)
// and relative offsets (-45..+45, where 0 is center)
void setPanAngle(float angleDeg) {
  int servoDeg;
  if (angleDeg < 0.0f) {
    // Negative offset from center: e.g. -35 deg -> 55 deg
    servoDeg = (int)(90.0f + angleDeg);
  } else if (angleDeg >= 20.0f && angleDeg <= 180.0f) {
    // Absolute servo angle: e.g. 35 (Rack A), 62 (B), 90 (C), 118 (D), 145 (E)
    servoDeg = (int)angleDeg;
  } else {
    // Small positive offset from center (0 to 19 deg): e.g. 0 -> 90 deg, +18 -> 108 deg
    servoDeg = (int)(90.0f + angleDeg);
  }

  if (servoDeg < 0) servoDeg = 0;
  if (servoDeg > 180) servoDeg = 180;
  currentPanAngle = (float)(servoDeg - 90);
  panServo.write(servoDeg);
}

// Command Parser
void handleSerialCommand(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line.startsWith("AIM,")) {
    // AIM,<pan>
    String angleStr = line.substring(4);
    float angle = angleStr.toFloat();
    setPanAngle(angle);
  } else if (line.startsWith("LASER,")) {
    // LASER,1 or LASER,0
    int state = line.substring(6).toInt();
    laserActive = (state == 1);
    digitalWrite(PIN_LASER_GATE, laserActive ? HIGH : LOW);
  }
}

void setup() {
  // Initialize USB CDC Serial
  Serial.begin(115200);

  // Power rails for Mics (eliminates need for breadboard power busses)
  pinMode(PIN_MIC_L_VCC, OUTPUT);
  pinMode(PIN_MIC_M_VCC, OUTPUT);
  pinMode(PIN_MIC_R_VCC, OUTPUT);
  digitalWrite(PIN_MIC_L_VCC, HIGH);
  digitalWrite(PIN_MIC_M_VCC, HIGH);
  digitalWrite(PIN_MIC_R_VCC, HIGH);

  // Laser Gate Pin
  pinMode(PIN_LASER_GATE, OUTPUT);
  digitalWrite(PIN_LASER_GATE, LOW);

  // ADC Setup (12-bit ADC: 0..4095)
  analogReadResolution(12);

  // Attach Pan Servo
  panServo.attach(PIN_PAN_SERVO);
  setPanAngle(0.0f); // Center

  delay(200);
}

void loop() {
  unsigned long frameStartUs = micros();
  unsigned long frameStartMs = millis();

  // 1. Process any incoming host serial commands (AIM / LASER)
  while (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    handleSerialCommand(cmd);
  }

  // 2. High-precision burst sampling: 256 samples per mic at 16 kHz
  // Each sample round across L, M, R is precisely spaced by 62.5 microseconds
  long meanL = 0, meanM = 0, meanR = 0;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    unsigned long sampleTargetUs = frameStartUs + (unsigned long)(i * SAMPLE_US);
    while ((long)(micros() - sampleTargetUs) < 0) {
      // Busy wait for microsecond-precise sampling cadence
    }

    int rawL = analogRead(PIN_MIC_L_AO);
    int rawM = analogRead(PIN_MIC_M_AO);
    int rawR = analogRead(PIN_MIC_R_AO);

    samplesL[i] = rawL;
    samplesM[i] = rawM;
    samplesR[i] = rawR;

    meanL += rawL;
    meanM += rawM;
    meanR += rawR;
  }

  // Remove DC bias (zero-center the analog audio signal)
  int16_t dcL = (int16_t)(meanL / NUM_SAMPLES);
  int16_t dcM = (int16_t)(meanM / NUM_SAMPLES);
  int16_t dcR = (int16_t)(meanR / NUM_SAMPLES);

  for (int i = 0; i < NUM_SAMPLES; i++) {
    samplesL[i] -= dcL;
    samplesM[i] -= dcM;
    samplesR[i] -= dcR;
  }

  // 3. Compute Goertzel energies for 2500 Hz (target beep), 2000 Hz, and 3000 Hz
  float L25 = computeGoertzel(samplesL, NUM_SAMPLES, COEFF_2500);
  float M25 = computeGoertzel(samplesM, NUM_SAMPLES, COEFF_2500);
  float R25 = computeGoertzel(samplesR, NUM_SAMPLES, COEFF_2500);

  float L20 = computeGoertzel(samplesL, NUM_SAMPLES, COEFF_2000);
  float M20 = computeGoertzel(samplesM, NUM_SAMPLES, COEFF_2000);
  float R20 = computeGoertzel(samplesR, NUM_SAMPLES, COEFF_2000);

  float L30 = computeGoertzel(samplesL, NUM_SAMPLES, COEFF_3000);
  float M30 = computeGoertzel(samplesM, NUM_SAMPLES, COEFF_3000);
  float R30 = computeGoertzel(samplesR, NUM_SAMPLES, COEFF_3000);

  // 4. Transmit Layer 2 serial frame:
  // E,<ms>,L25,M25,R25,L20,M20,R20,L30,M30,R30
  Serial.print("E,");
  Serial.print(frameStartMs);
  Serial.print(",");
  Serial.print(L25, 2);
  Serial.print(",");
  Serial.print(M25, 2);
  Serial.print(",");
  Serial.print(R25, 2);
  Serial.print(",");
  Serial.print(L20, 2);
  Serial.print(",");
  Serial.print(M20, 2);
  Serial.print(",");
  Serial.print(R20, 2);
  Serial.print(",");
  Serial.print(L30, 2);
  Serial.print(",");
  Serial.print(M30, 2);
  Serial.print(",");
  Serial.println(R30, 2);

  // 5. Enforce 50 Hz frame rate (20,000 microseconds per iteration)
  unsigned long elapsedUs = micros() - frameStartUs;
  if (elapsedUs < 20000) {
    delayMicroseconds(20000 - elapsedUs);
  }
}

