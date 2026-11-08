// Beacon turret firmware: pan servo on GP15, laser switch on GP13.
// The Pico only moves the servo and the laser. The laptop decides everything.
//
// Commands from the laptop, one per line:
//   AIM,<deg>    glide to an angle (laser stays as it is)
//   LOCK,<deg>   laser off, glide there, blink 3 times, then laser on
//   LASER,<0|1>  laser off / on (stays on until you turn it off)
//   LASER?       report whether the laser is on
//   AUTOOFF,<s>  turn the laser off by itself after s seconds; AUTOOFF,0 = never (the default)
//   JOG,<deg>    nudge by a few degrees, e.g. JOG,1 or JOG,-1
//   HOME         laser off, glide to the saved center (90 until you save one)
//   POS?         report the current angle
//   SETHOME      save the current angle as the center; it survives unplugging
//   HOME?        report the saved center
//   SWING,<deg>  laser on, swing center-deg <-> center+deg twice, then back to center
//   MIC,<0|1>    stop / start streaming the 3 mics (off by default so the monitor stays readable)
// While MIC is on, about 55 lines a second:
//   E,<ms>,L2500,M2500,R2500,L2000,M2000,R2000,L3000,M3000,R3000   (2500 Hz is the beep, the others are reference)
// Replies: READY, POS,<deg>, OK,MIC,<0|1>, OK,LASER, LASER,<0|1>, OK,AUTOOFF,<s>, OK,HOME,<deg>, HOME,<deg>, ERR,<reason>

#include <Servo.h>
#include <EEPROM.h>

const int SERVO_PIN = 15;
const int LASER_PIN = 13;
const float MIN_DEG = 10.0;
const float MAX_DEG = 170.0;
const float HOME_DEG = 90.0;
const float APPROACH_DEG = 6.0;       // always arrive from 6 degrees below, so gear slop is the same every time
const unsigned long MS_PER_DEG = 10;  // glide speed, about 2 degrees per servo frame
const unsigned long CREEP_MS_PER_DEG = 25;
const unsigned long FRAME_MS = 20;    // the servo only listens every 20 ms anyway
unsigned long laserTimeoutMs = 0;     // 0 = the laser stays on until LASER,0 or HOME

// mics: L on GP26, M on GP27, R on GP28, each powered from its own pin so no breadboard is needed
const int MIC_PINS[3] = {26, 27, 28};
const int MIC_POWER[3] = {2, 3, 4};
const int N = 256;                    // 256 samples per mic = 16 ms at 16 kHz
bool micOn = false;
int raw[3][N];

const uint32_t HOME_MAGIC = 0xBEAC0001;  // marks that a center was saved on purpose

struct SavedHome {
  uint32_t magic;
  float deg;
};

Servo pan;
float homeDeg = HOME_DEG;
float currentDeg = HOME_DEG;
bool laserOn = false;
unsigned long laserSince = 0;
String line;

void writeServo(float deg) {
  // 500 us = 0 degrees, 2400 us = 180 degrees (the same range we attach with)
  int us = (int)(500.0f + deg * (1900.0f / 180.0f) + 0.5f);
  pan.writeMicroseconds(us);
}

void setLaser(bool on) {
  laserOn = on;
  digitalWrite(LASER_PIN, on ? HIGH : LOW);
  if (on) laserSince = millis();
}

// smooth start and stop, so the servo never snaps and the current stays low
void glideTo(float target, unsigned long msPerDeg) {
  float start = currentDeg;
  float dist = fabsf(target - start);
  if (dist < 0.05f) {
    currentDeg = target;
    writeServo(target);
    return;
  }
  unsigned long duration = (unsigned long)(dist * msPerDeg);
  if (duration < 100) duration = 100;
  unsigned long t0 = millis();
  while (millis() - t0 < duration) {
    float u = (float)(millis() - t0) / duration;
    float s = u * u * (3.0f - 2.0f * u);
    writeServo(start + (target - start) * s);
    delay(FRAME_MS);
  }
  currentDeg = target;
  writeServo(target);
}

// every aim ends with the same slow upward creep, so a saved angle lands on the same spot
void approach(float target) {
  float below = target - APPROACH_DEG;
  if (below < MIN_DEG) below = MIN_DEG;  // at the very bottom we can't come from below, get as close as we can
  glideTo(below, MS_PER_DEG);
  glideTo(target, CREEP_MS_PER_DEG);
}

void loadHome() {
  SavedHome saved;
  EEPROM.get(0, saved);
  if (saved.magic == HOME_MAGIC && saved.deg >= MIN_DEG && saved.deg <= MAX_DEG) {
    homeDeg = saved.deg;
  }
}

void saveHome(float deg) {
  SavedHome saved = {HOME_MAGIC, deg};
  EEPROM.put(0, saved);
  EEPROM.commit();
  homeDeg = deg;
}

// amplitude (in ADC counts) of one frequency; bin k = freq * N / 16000 (2500 Hz -> 40)
float goertzelAmp(const int *samples, float mean, int k) {
  float coeff = 2.0f * cosf(2.0f * PI * k / N);
  float s1 = 0, s2 = 0;
  for (int i = 0; i < N; i++) {
    float s = (samples[i] - mean) + coeff * s1 - s2;
    s2 = s1;
    s1 = s;
  }
  float power = s1 * s1 + s2 * s2 - coeff * s1 * s2;
  if (power < 0) power = 0;
  return 2.0f * sqrtf(power) / N;
}

// one 16 ms frame from all 3 mics, then one E line
void streamFrame() {
  unsigned long t0 = micros();
  for (int i = 0; i < N; i++) {
    unsigned long due = t0 + (unsigned long)i * 125UL / 2UL;  // every 62.5 us
    while ((long)(micros() - due) < 0) { }
    for (int m = 0; m < 3; m++) raw[m][i] = analogRead(MIC_PINS[m]);
  }
  const int bins[3] = {40, 32, 48};  // 2500, 2000, 3000 Hz
  Serial.print("E,");
  Serial.print(millis());
  for (int b = 0; b < 3; b++) {
    for (int m = 0; m < 3; m++) {
      float mean = 0;
      for (int i = 0; i < N; i++) mean += raw[m][i];
      mean /= N;
      Serial.print(',');
      Serial.print(goertzelAmp(raw[m], mean, bins[b]), 3);
    }
  }
  Serial.println();
}

void reportPos() {
  Serial.print("POS,");
  Serial.println(currentDeg, 1);
}

bool parseDeg(const String &arg, float &out) {
  // toFloat() returns 0 for garbage, so make sure there is at least one digit
  bool digit = false;
  for (unsigned int i = 0; i < arg.length(); i++) {
    if (isDigit(arg[i])) digit = true;
  }
  if (!digit) return false;
  out = arg.toFloat();
  return true;
}

void handle(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;
  cmd.toUpperCase();
  int comma = cmd.indexOf(',');
  String name = comma < 0 ? cmd : cmd.substring(0, comma);
  String arg = comma < 0 ? "" : cmd.substring(comma + 1);
  float deg = 0;

  if (name == "POS?") {
    reportPos();
    return;
  }

  if (name == "HOME?") {
    Serial.print("HOME,");
    Serial.println(homeDeg, 1);
    return;
  }

  if (name == "SETHOME") {
    saveHome(currentDeg);
    Serial.print("OK,HOME,");
    Serial.println(homeDeg, 1);
    return;
  }

  if (name == "HOME") {
    setLaser(false);
    approach(homeDeg);
    reportPos();
    return;
  }

  if (name == "SWING") {
    if (!parseDeg(arg, deg) || deg <= 0) {
      Serial.println("ERR,bad_number");
      return;
    }
    if (homeDeg - deg < MIN_DEG || homeDeg + deg > MAX_DEG) {
      Serial.println("ERR,out_of_range");
      return;
    }
    setLaser(true);
    for (int i = 0; i < 2; i++) {
      approach(homeDeg - deg);
      delay(400);
      approach(homeDeg + deg);
      delay(400);
    }
    approach(homeDeg);
    setLaser(false);
    reportPos();
    return;
  }

  if (name == "MIC") {
    if (arg == "1") micOn = true;
    else if (arg == "0") micOn = false;
    else {
      Serial.println("ERR,mic_needs_0_or_1");
      return;
    }
    Serial.println(micOn ? "OK,MIC,1" : "OK,MIC,0");
    return;
  }

  if (name == "LASER?") {
    Serial.print("LASER,");
    Serial.println(laserOn ? 1 : 0);
    return;
  }

  if (name == "AUTOOFF") {
    if (!parseDeg(arg, deg) || deg < 0) {
      Serial.println("ERR,bad_number");
      return;
    }
    laserTimeoutMs = (unsigned long)(deg * 1000.0f);
    Serial.print("OK,AUTOOFF,");
    Serial.println((int)deg);
    return;
  }

  if (name == "LASER") {
    if (arg == "1") setLaser(true);
    else if (arg == "0") setLaser(false);
    else {
      Serial.println("ERR,laser_needs_0_or_1");
      return;
    }
    Serial.println("OK,LASER");
    return;
  }

  if (name == "AIM" || name == "LOCK" || name == "JOG") {
    if (!parseDeg(arg, deg)) {
      Serial.println("ERR,bad_number");
      return;
    }
    float target = (name == "JOG") ? currentDeg + deg : deg;
    if (target < MIN_DEG || target > MAX_DEG) {
      Serial.println("ERR,out_of_range");
      return;
    }

    if (name == "LOCK") {
      setLaser(false);
      approach(target);
      for (int i = 0; i < 3; i++) {  // the lock-on blink
        digitalWrite(LASER_PIN, HIGH);
        delay(90);
        digitalWrite(LASER_PIN, LOW);
        delay(90);
      }
      setLaser(true);
    } else if (name == "AIM") {
      approach(target);
      if (laserOn) laserSince = millis();
    } else {
      // jogs go straight there, so calibration can finish with an upward jog like the firmware does
      glideTo(target, MS_PER_DEG);
      if (laserOn) laserSince = millis();
    }
    reportPos();
    return;
  }

  Serial.println("ERR,unknown_command");
}

void setup() {
  pinMode(LASER_PIN, OUTPUT);
  setLaser(false);
  for (int m = 0; m < 3; m++) {
    pinMode(MIC_POWER[m], OUTPUT);
    digitalWrite(MIC_POWER[m], HIGH);
  }
  analogReadResolution(12);
  EEPROM.begin(64);
  loadHome();
  pan.attach(SERVO_PIN, 500, 2400);
  writeServo(homeDeg);
  currentDeg = homeDeg;
  Serial.begin(115200);
  delay(300);
  Serial.println("READY");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (line.length() > 0) {
        handle(line);
        line = "";
      }
    } else if (line.length() < 40) {
      line += c;
    }
  }
  if (micOn) streamFrame();
  // optional failsafe: only if AUTOOFF was set to something above 0
  if (laserOn && laserTimeoutMs > 0 && millis() - laserSince > laserTimeoutMs) {
    setLaser(false);
  }
}
