# 교실 환경센서 대시보드 + 리포트 스킬

교사연구회 2차 과제 · ESP32로 교실 공기(CO₂·온도·습도·기압·VOC)를 재서 라즈베리파이에 쌓고,
대시보드로 보여 주고, **"센서 데이터 → 분석 리포트"** 과정을 Claude Code 스킬로 만들었습니다.

- 📊 **대시보드**: https://dew-classroom-air.netlify.app
- 🧩 **스킬**: [`skills/env-sensor-report`](skills/env-sensor-report/SKILL.md)
- 📄 **리포트 예시**: [`sample_data/report_env_data/report.md`](sample_data/report_env_data/report.md)

## 구성

```
[CO2L 센서 SCD41] ─ I2C 소켓 ─┐
                              ├─ [Arduino Nano ESP32] ── USB 시리얼 ──> [라즈베리파이 5]
[ENV Pro 센서 BME688] ─ D2 소켓 ┘        (Wi-Fi HTTP도 지원)          usb_bridge.py → server.py
                                                                       → env_data.csv
                                                                       → 대시보드 :5000
                                                                       → build_netlify.py → Netlify
```

| 부품 | 역할 |
|---|---|
| Arduino Nano ESP32 + Grove 실드 | 센서 읽기, 30초마다 전송 |
| M5Stack CO2L Unit (SCD41) | CO₂ · 온도 · 습도 |
| M5Stack ENV Pro Unit (BME688) | 온도 · 습도 · 기압 · 가스 저항(VOC) |
| Raspberry Pi 5 | 데이터 수신·저장, 대시보드 서빙 |

## 폴더

| 경로 | 내용 |
|---|---|
| `step1_sensor_test/` | Step 1 · 두 센서 값을 시리얼 모니터에 출력 |
| `step2_send_to_pi/` | Step 2 · 30초마다 파이로 전송 (Wi-Fi HTTP 또는 USB 시리얼), 워치독 포함 |
| `pi_server/server.py` | 파이 · 데이터 수신(POST `/api/data`) + CSV 저장 + 대시보드 서빙 |
| `pi_server/usb_bridge.py` | 파이 · USB 시리얼의 `DATA {json}` 줄을 server.py로 전달 |
| `pi_server/dashboard.html` | 실시간 대시보드 (30초 자동 갱신) |
| `pi_server/build_netlify.py` | 데이터·그래프 라이브러리를 넣은 단일 `index.html` 생성 (Netlify용) |
| `dashboard/index.html` | Netlify에 배포한 파일 |
| `skills/env-sensor-report/` | Step 4 · 리포트 스킬 (SKILL.md + scripts/analyze.py) |
| `sample_data/` | 실제 측정 데이터 584건과 생성된 리포트, 형식 테스트용 CSV |

## 따라 하기

### 1. 펌웨어 (Arduino IDE 또는 arduino-cli)
- 보드: **Arduino Nano ESP32** (`arduino:esp32:nano_nora`)
- 라이브러리: `Adafruit BME680 Library`, `Sensirion I2C SCD4x`
- 실드의 I2C 소켓이 1개뿐이라 BME688은 **D2 소켓**에 꽂고 두 번째 I2C 버스(`Wire1`, SDA=D3·SCL=D2)로 읽습니다.
- `step2_send_to_pi.ino`의 설정 칸에서 `USE_WIFI`, Wi-Fi 이름·비밀번호, 파이 주소를 바꿉니다.

### 2. 라즈베리파이
```bash
mkdir -p ~/esp32-env && cd ~/esp32-env    # pi_server/ 파일을 여기에 복사
python3 server.py &                        # http://<파이IP>:5000
python3 usb_bridge.py &                    # ESP32를 USB로 연결했을 때
# 부팅 시 자동 시작 (crontab -e)
# @reboot sleep 15 && /usr/bin/python3 /home/<사용자>/esp32-env/server.py >> /home/<사용자>/esp32-env/server.log 2>&1
# @reboot sleep 20 && /usr/bin/python3 /home/<사용자>/esp32-env/usb_bridge.py >> /home/<사용자>/esp32-env/usb_bridge.log 2>&1
```
파이썬 표준 라이브러리만 써서 추가 설치가 없습니다.

### 3. Netlify 배포
```bash
python3 pi_server/build_netlify.py env_data.csv dashboard   # dashboard/index.html 생성
```
`dashboard` 폴더를 https://app.netlify.com/drop 에 끌어다 놓습니다.

### 4. 리포트 스킬
`skills/env-sensor-report` 폴더를 `~/.claude/skills/`에 복사하면 Claude Code에서
"이 CSV로 리포트 만들어줘"라고 말해 사용할 수 있습니다. 직접 실행도 됩니다.
```bash
python3 skills/env-sensor-report/scripts/analyze.py sample_data/env_data.csv --title "교실 환경 분석 리포트"
```

## 겪은 문제와 해결 (연구회 공유용)

| 문제 | 원인 | 해결 |
|---|---|---|
| ESP32 → 파이 전송이 `connection refused` | **학교 Wi-Fi가 기기 간 통신을 차단**(클라이언트 격리) | ESP32를 파이 USB에 꽂아 시리얼로 전달 (`usb_bridge.py`). 공유기·핫스팟에서는 Wi-Fi로 동작 |
| 실드에 I2C 소켓이 1개 | — | ESP32의 두 번째 I2C 버스를 D2 소켓 핀에 배정 |
| 업로드 실패 `exit status 74` | Nano ESP32 DFU 드라이버 미설치 / 연결 꼬임 | 드라이버 설치(`dpinst-amd64.exe`), USB 다시 꽂은 직후 업로드 |
| 며칠 뒤 수집이 멈춤 | ESP32가 Wi-Fi 재접속 중 멈춤 | Wi-Fi 끄고(USB 전용) **워치독**(90초) 추가 |
| 파이 IP가 자꾸 바뀌고 접속이 끊김 | 학교 Wi-Fi의 여러 공유기·IP 재할당 | 같은 SSID에 연결 후 MAC 주소로 파이 찾기 |
| 대시보드 그래프가 빈 화면 | CDN 차단 · 파일로 열 때 외부 스크립트 막힘 | 그래프 라이브러리를 HTML 안에 포함 |

## 측정 결과 요약 (2026-10-20 ~ 10-26, 584건)
CO₂ 평균 539ppm(최대 824), 온도 18.8~24.2℃, 습도 40.7~60.3% — 측정 구간 내 학교 공기질 기준 이탈 없음.
다만 대부분 밤 시간 데이터라 수업 중 공기질 판단에는 낮 시간 측정이 더 필요합니다. 자세한 내용은 [리포트](sample_data/report_env_data/report.md) 참고.
