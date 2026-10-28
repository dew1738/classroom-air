/*
  Step 2 - 센서값을 Wi-Fi로 라즈베리파이에 전송 (HTTP POST, 30초마다)
  보드  : Arduino Nano ESP32 + Grove 실드
  센서1 : M5Stack ENV Pro Unit (BME688, 0x77) → 실드 D2 소켓 (두 번째 I2C 버스 Wire1)
  센서2 : M5Stack CO2L Unit   (SCD41, 0x62)  → 실드 I2C 소켓 (기본 I2C 버스 Wire)
  받는 곳: 라즈베리파이 server.py  →  http://<파이>:5000/api/data

  필요한 라이브러리: Step 1과 같음 (Adafruit BME680 Library, Sensirion I2C SCD4x)
  ★ 아래 "설정" 부분만 고치면 된다.
*/
#include <Wire.h>
#include <WiFi.h>
#include <WiFiMulti.h>
#include <HTTPClient.h>
#include <ESPmDNS.h>
#include <Adafruit_BME680.h>
#include <SensirionI2cScd4x.h>
#include <esp_task_wdt.h>

// ===================== 설정 =====================
// 학교 Wi-Fi는 기기 간 통신을 막아 Wi-Fi 전송이 불가 → USB 시리얼로만 보낸다.
// 공유기·핫스팟처럼 통신되는 Wi-Fi에서는 true로 바꾸면 Wi-Fi로 보낸다.
const bool USE_WIFI = false;
// Wi-Fi는 여러 개 등록 가능 → 잡히는 곳에 자동 연결 (2.4GHz만 지원)
const char* WIFI_LIST[][2] = {
  {"와이파이이름1", "비밀번호1"},  // ★ 실제 Wi-Fi 이름·비밀번호로 바꿔서 업로드
  // {"와이파이이름2", "비밀번호2"},
};
const char* PI_HOSTNAME = "dew";             // 파이 호스트 이름 (dew.local)
IPAddress   PI_FALLBACK_IP(192, 168, 1, 43);  // 이름으로 못 찾을 때 쓸 IP
const int   PI_PORT = 5000;
const char* DEVICE_NAME = "classroom-1";      // 기기 이름 (여러 대일 때 구분용)
const unsigned long SEND_INTERVAL_MS = 30000; // 전송 주기 30초
// =================================================

WiFiMulti wifiMulti;
Adafruit_BME680 bme(&Wire1);  // ENV Pro는 두 번째 버스(Wire1)
SensirionI2cScd4x scd;
bool bmeOk = false, scdOk = false;

// D2 소켓: 노란선=D2, 흰선=D3. 방향이 반대일 수 있어 두 방향 모두 시도
bool beginBme() {
  Wire1.begin(D3, D2);  // SDA=D3, SCL=D2
  if (bme.begin(0x77)) return true;
  Wire1.end();
  Wire1.begin(D2, D3);
  return bme.begin(0x77);
}

// SCD41은 5초마다 새 값이 나오므로 마지막 값을 기억해 둔다
uint16_t lastCo2 = 0;
float lastScdT = NAN, lastScdH = NAN;

IPAddress piIp = PI_FALLBACK_IP;

void connectWiFi() {
  if (!USE_WIFI || WiFi.status() == WL_CONNECTED) return;
  Serial.print("Wi-Fi 연결 중");
  unsigned long start = millis();
  while (wifiMulti.run() != WL_CONNECTED && millis() - start < 20000) {
    Serial.print(".");
    delay(500);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n연결됨: %s  내 IP %s\n", WiFi.SSID().c_str(), WiFi.localIP().toString().c_str());
    // 파이 IP를 이름(dew.local)으로 찾기 → 실패하면 고정 IP 사용
    static bool mdnsStarted = false;
    if (!mdnsStarted) mdnsStarted = MDNS.begin(DEVICE_NAME);
    IPAddress found = MDNS.queryHost(PI_HOSTNAME, 3000);
    if (found != IPAddress(0, 0, 0, 0)) piIp = found;
    Serial.printf("파이 주소: %s\n", piIp.toString().c_str());
  } else {
    Serial.println("\nWi-Fi 연결 실패 - 이름/비밀번호, 2.4GHz 여부 확인");
  }
}

void readScd() {
  if (!scdOk) return;
  bool ready = false;
  scd.getDataReadyStatus(ready);
  if (!ready) return;
  uint16_t co2; float t, h;
  if (scd.readMeasurement(co2, t, h) == 0 && co2 > 0) {
    lastCo2 = co2; lastScdT = t; lastScdH = h;
  }
}

// 값이 없으면 JSON에 null로 넣는다
String num(float v, int digits) { return isnan(v) ? "null" : String(v, digits); }

void sendToPi() {
  String json = "{";
  json += "\"device\":\"" + String(DEVICE_NAME) + "\"";
  if (bmeOk && bme.performReading()) {
    json += ",\"temp_c\":" + num(bme.temperature, 2);
    json += ",\"humidity\":" + num(bme.humidity, 2);
    json += ",\"pressure_hpa\":" + num(bme.pressure / 100.0, 2);
    json += ",\"gas_kohm\":" + num(bme.gas_resistance / 1000.0, 2);
  }
  if (lastCo2 > 0) {
    json += ",\"co2_ppm\":" + String(lastCo2);
    json += ",\"scd_temp_c\":" + num(lastScdT, 2);
    json += ",\"scd_humidity\":" + num(lastScdH, 2);
  }
  json += "}";

  int code = -1;
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    String url = "http://" + piIp.toString() + ":" + PI_PORT + "/api/data";
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(5000);
    code = http.POST(json);
    Serial.printf("[내 IP %s] 전송 %s → %d %s\n", WiFi.localIP().toString().c_str(), url.c_str(), code,
                  code < 0 ? http.errorToString(code).c_str() : "");
    http.end();
  }
  // Wi-Fi 전송이 실패하면 USB 시리얼로 내보낸다 → 파이의 usb_bridge.py가 받아 저장
  // (Wi-Fi가 성공하면 출력하지 않아 중복 저장을 막는다)
  if (code != 200) Serial.println("DATA " + json);
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000) {}

  Wire.begin();  // 실드 I2C 소켓 (CO2L)
  bmeOk = beginBme();
  if (bmeOk) {
    bme.setTemperatureOversampling(BME680_OS_8X);
    bme.setHumidityOversampling(BME680_OS_2X);
    bme.setPressureOversampling(BME680_OS_4X);
    bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
    bme.setGasHeater(320, 150);
  }
  Serial.println(bmeOk ? "BME688 OK" : "BME688 연결 실패");

  scd.begin(Wire, SCD41_I2C_ADDR_62);
  scd.wakeUp();
  scd.stopPeriodicMeasurement();
  scd.reinit();
  scdOk = (scd.startPeriodicMeasurement() == 0);
  Serial.println(scdOk ? "SCD41 OK" : "SCD41 연결 실패");

  if (USE_WIFI) {
    WiFi.mode(WIFI_STA);
    for (auto& w : WIFI_LIST) wifiMulti.addAP(w[0], w[1]);
    connectWiFi();
  } else {
    WiFi.mode(WIFI_OFF);
  }

  // 워치독: loop가 90초 넘게 멈추면 보드를 자동 재시작한다 (10/23 새벽 멈춤 사고 대비)
  esp_task_wdt_init(90, true);
  esp_task_wdt_add(NULL);
}

unsigned long lastSend = 0;

void loop() {
  esp_task_wdt_reset();  // "아직 살아 있음" 신호
  readScd();
  if (millis() - lastSend >= SEND_INTERVAL_MS || lastSend == 0) {
    if (lastSend == 0 && lastCo2 == 0 && millis() < 15000) { delay(1000); return; }  // 첫 CO2 값 대기
    lastSend = millis();
    connectWiFi();  // 끊겼으면 다시 연결
    sendToPi();
  }
  delay(1000);
}
