// Servo test: pan servo signal on GP15
#include <Servo.h>

Servo pan;

void setup() {
  pan.attach(15, 500, 2400);
}

void loop() {
  pan.write(60);
  delay(1000);
  pan.write(120);
  delay(1000);
}
