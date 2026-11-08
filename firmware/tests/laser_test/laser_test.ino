// Laser test: GP13 switches the transistor, which switches the laser
const int LASER = 13;

void setup() {
  pinMode(LASER, OUTPUT);
}

void loop() {
  digitalWrite(LASER, HIGH);
  delay(250);
  digitalWrite(LASER, LOW);
  delay(250);
}
