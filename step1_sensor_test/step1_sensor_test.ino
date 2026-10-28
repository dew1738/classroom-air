/*
  Step 1 - 센서 테스트 (시리얼 모니터 출력)
  보드  : Arduino Nano ESP32 + Grove 실드
  센서1 : M5Stack ENV Pro Unit (BME688, 0x77) → 실드 D2 소켓 (두 번째 I2C 버스 Wire1로 사용)
  센서2 : M5Stack CO2L Unit   (SCD41, 0x62)  → 실드 I2C 소켓 (기본 I2C 버스 Wire)
  ※ 실드에 I2C 소켓이 1개뿐이라, ESP32의 두 번째 I2C를 D2 소켓 핀(D2·D3)에 배정했다.

  필요한 라이브러리 (Arduino IDE > 라이브러리 매니저에서 검색·설치)
    - "Adafruit BME680 Library"  (BME688도 지원)
    - "Sensirion I2C SCD4x"      (SCD40/SCD41 공용)

  시리얼 모니터 속도: 115200
*/
#include <Wire.h>
#include <Adafruit_BME680.h>
#include <SensirionI2cScd4x.h>

Adafruit_BME680 bme(&Wire1);  // ENV Pro는 두 번째 버스(Wire1)
SensirionI2cScd4x scd;

bool bmeOk = false;
bool scdOk = false;

// I2C 버스에 연결된 장치 주소를 모두 출력 (연결 확인용)
void scanI2C(TwoWire& bus, const char* name) {
  Serial.printf("%s 스캔 중...\n", name);
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    bus.beginTransmission(addr);
    if (bus.endTransmission() == 0) {
      Serial.printf("  발견: 0x%02X\n", addr);
      found++;
    }
  }
  if (found == 0) Serial.println("  장치 없음 - 케이블이 제대로 꽂혔는지 확인");
}

// D2 소켓: 노란선=D2, 흰선=D3. Grove I2C는 노란선=SCL, 흰선=SDA.
// 혹시 반대일 수 있어 두 방향을 모두 시도한다.
bool beginBme() {
  Wire1.begin(D3, D2);  // SDA=D3, SCL=D2
  if (bme.begin(0x77)) return true;
  Wire1.end();
  Wire1.begin(D2, D3);  // 반대 방향
  return bme.begin(0x77);
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 5000) {}  // USB 시리얼 연결 대기 (최대 5초)
  delay(500);

  Wire.begin();  // 실드 I2C 소켓 = Nano ESP32 기본 I2C: A4(SDA), A5(SCL)
  scanI2C(Wire, "I2C 소켓(CO2L, 0x62 정상)");

  // --- BME688 ---
  bmeOk = beginBme();
  scanI2C(Wire1, "D2 소켓(ENV Pro, 0x77 정상)");
  if (bmeOk) {
    bme.setTemperatureOversampling(BME680_OS_8X);
    bme.setHumidityOversampling(BME680_OS_2X);
    bme.setPressureOversampling(BME680_OS_4X);
    bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
    bme.setGasHeater(320, 150);  // 320°C로 150ms 가열 후 가스저항 측정
    Serial.println("BME688 OK");
  } else {
    Serial.println("BME688 연결 실패");
  }

  // --- SCD41 ---
  scd.begin(Wire, SCD41_I2C_ADDR_62);
  scd.wakeUp();
  scd.stopPeriodicMeasurement();  // 이전 측정이 돌고 있으면 정지
  scd.reinit();
  int16_t err = scd.startPeriodicMeasurement();  // 5초마다 측정
  scdOk = (err == 0);
  Serial.println(scdOk ? "SCD41 OK (첫 값은 약 5초 후)" : "SCD41 연결 실패");
}

void loop() {
  Serial.println("----------------------------------------");

  if (bmeOk && bme.performReading()) {
    Serial.printf("[BME688] 온도 %.2f °C | 습도 %.2f %% | 기압 %.2f hPa | 가스 %.1f kΩ\n",
                  bme.temperature, bme.humidity, bme.pressure / 100.0, bme.gas_resistance / 1000.0);
  } else {
    Serial.println("[BME688] 읽기 실패");
  }

  if (scdOk) {
    bool ready = false;
    scd.getDataReadyStatus(ready);
    if (ready) {
      uint16_t co2 = 0;
      float t = 0, h = 0;
      if (scd.readMeasurement(co2, t, h) == 0) {
        Serial.printf("[SCD41 ] CO2 %u ppm | 온도 %.2f °C | 습도 %.2f %%\n", co2, t, h);
      } else {
        Serial.println("[SCD41 ] 읽기 실패");
      }
    } else {
      Serial.println("[SCD41 ] 측정 대기 중...");
    }
  }

  delay(5000);
}
