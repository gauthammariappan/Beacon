// Goertzel check: how strong is the 2500 Hz beep compared with the frequencies next to it?
// One mic on GP26, powered from GP2. Prints E,<ms>,<2500 Hz>,<2000 Hz>,<3000 Hz>,<frame us>
const int MIC_PIN = 26;
const int MIC_POWER = 2;
const int N = 256;          // samples per frame, 16 ms at 16 kHz

int raw[N];
float x[N];

// amplitude (in ADC counts) of one frequency bin; bin k = freq * N / 16000
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
  analogReadResolution(12);
}

void loop() {
  unsigned long t0 = micros();
  for (int i = 0; i < N; i++) {
    // one sample every 62.5 us = 16,000 samples per second
    unsigned long due = t0 + (unsigned long)i * 125UL / 2UL;
    while ((long)(micros() - due) < 0) { }
    raw[i] = analogRead(MIC_PIN);
  }
  unsigned long frameUs = micros() - t0;

  float mean = 0;
  for (int i = 0; i < N; i++) mean += raw[i];
  mean /= N;
  for (int i = 0; i < N; i++) x[i] = raw[i] - mean;   // remove the DC offset

  float a2500 = goertzelAmp(40);
  float a2000 = goertzelAmp(32);
  float a3000 = goertzelAmp(48);

  Serial.print("E,");
  Serial.print(millis());   Serial.print(',');
  Serial.print(a2500, 3);   Serial.print(',');
  Serial.print(a2000, 3);   Serial.print(',');
  Serial.print(a3000, 3);   Serial.print(',');
  Serial.println(frameUs);
  delay(4);
}
