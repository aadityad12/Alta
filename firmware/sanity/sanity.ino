// Pod wiring sanity test (#5). Throwaway Arduino sketch, not the real firmware (#6/#7).
// Wiring: firmware/WIRING.md. Run it with firmware/sanity/check_pod.py.
//
// Prints one line every 200 ms at 115200 baud:
//   Y=0 B=1023 G=511 W=3 btn=1 led=R
// Y/B/G/W = raw analogRead of A0..A3 (0 = GND, 1023 = 5 V); btn = digitalRead(D2)
// with the internal pull-up (0 = pressed); led = the color the status LED
// should be showing right now (it cycles R, G, B, off once a second).
// Send 'i' to invert the LED outputs (common-anode LED); the line then ends in " inv".

const uint8_t PROBES[4] = {A0, A1, A2, A3};
const char *NAMES[4] = {"Y", "B", "G", "W"};
const uint8_t BTN = 2;
const uint8_t LED_PINS[3] = {9, 10, 11};  // R, G, B
const char *COLORS[4] = {"R", "G", "B", "off"};

bool invert = false;
uint8_t color = 0;
unsigned long lastColor = 0;

void showColor() {
  for (uint8_t i = 0; i < 3; i++) {
    bool on = (i == color);
    digitalWrite(LED_PINS[i], (on != invert) ? HIGH : LOW);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(BTN, INPUT_PULLUP);
  for (uint8_t i = 0; i < 3; i++) pinMode(LED_PINS[i], OUTPUT);
  showColor();
  Serial.println(F("# bench pod sanity test"));
}

void loop() {
  while (Serial.available()) {
    if (Serial.read() == 'i') { invert = !invert; showColor(); }
  }
  if (millis() - lastColor >= 1000) {
    lastColor = millis();
    color = (color + 1) % 4;
    showColor();
  }
  for (uint8_t i = 0; i < 4; i++) {
    Serial.print(NAMES[i]); Serial.print('='); Serial.print(analogRead(PROBES[i])); Serial.print(' ');
  }
  Serial.print(F("btn=")); Serial.print(digitalRead(BTN));
  Serial.print(F(" led=")); Serial.print(COLORS[color]);
  if (invert) Serial.print(F(" inv"));
  Serial.println();
  delay(200);
}
