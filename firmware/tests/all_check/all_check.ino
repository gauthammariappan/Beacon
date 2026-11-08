// All-in-one check: mic L streams its 2500 Hz energy, the servo swings, the laser stays on.
// Prints E,<ms>,<2500 Hz>,<2000 Hz>,<3000 Hz>,<frame us>
#include <Servo.h>

const int MIC_PIN = 26;
const int MIC_POWER = 2;
const int LASER = 13;
const int SERVO_PIN = 15;
const int N = 256;          // 16 ms of samples at 16 kHz

int raw[N];
float x[N];
Servo pan;
unsigned long lastMove = 0;
bool leftSide = false;

float goertzelAmp(int k) {
  float coeff = 2.0f * cosf(2.0f * PI * k / N);
  float s1 = 0, s2 = 0;
  for (int i = 0; i < N; i++) {
    float s = x[i] + coeff * s1 - s2;
    s2 = s1;
    s1 = s;
  }
  float power = s1 * s1 + s2 * s2 - coeff * s1 * s2;
  if (power < 0) power = 0;
  return 2.0f * sqrtf(power) / N;
}

void setup() {
  Serial.begin(115200);
  pinMode(MIC_POWER, OUTPUT);
  digitalWrite(MIC_POWER, HIGH);
  pinMode(LASER, OUTPUT);
  digitalWrite(LASER, HIGH);
  analogReadResolution(12);
  pan.attach(SERVO_PIN, 500, 2400);
  pan.write(90);
}

void loop() {
  // swing the servo every 1.5 s so we can see whether it disturbs the mic
  if (millis() - lastMove > 1500) {
    leftSide = !leftSide;
    pan.write(leftSide ? 70 : 110);
    lastMove = millis();
  }

  unsigned long t0 = micros();
  for (int i = 0; i < N; i++) {
    unsigned long due = t0 + (unsigned long)i * 125UL / 2UL;
    while ((long)(micros() - due) < 0) { }
    raw[i] = analogRead(MIC_PIN);
  }
  unsigned long frameUs = micros() - t0;

  float mean = 0;
  for (int i = 0; i < N; i++) mean += raw[i];
  mean /= N;
  for (int i = 0; i < N; i++) x[i] = raw[i] - mean;

  Serial.print("E,");
  Serial.print(millis());         Serial.print(',');
  Serial.print(goertzelAmp(40), 3); Serial.print(',');
  Serial.print(goertzelAmp(32), 3); Serial.print(',');
  Serial.print(goertzelAmp(48), 3); Serial.print(',');
  Serial.println(frameUs);
  delay(4);
}
