# IoT Health Edge MVP

Prototype học tập **phi lâm sàng** dùng NodeMCU ESP8266, MAX30102, cảm biến
chuyển động MPU-6050 hoặc MPU-6500-compatible và DS18B20 tiếp xúc bề mặt cổ tay. Node gửi dữ liệu có
cờ chất lượng qua MQTT; laptop nhận, lưu SQLite, áp dụng luật cảnh báo demo và
hiển thị dashboard tiếng Việt.

Không dùng kết quả để chẩn đoán, điều trị, quyết định cấp cứu hoặc thay thế
thiết bị y tế. DS18B20 chỉ cung cấp nhiệt độ **bề mặt tại điểm tiếp xúc** cho
prototype; giá trị này không phải nhiệt độ cơ thể/lõi, không dùng để kết luận
sốt và không kích hoạt cảnh báo nhiệt độ.

## Định vị đồ án NT532

Tên đề tài MVP:

> **Đánh giá độ tin cậy xử lý bản tin MQTT trong hệ thống IoT edge phi lâm sàng
> dưới lỗi cảm biến và lỗi ở tầng ứng dụng**

Đồ án được định vị theo hướng **IoT Protocol** của môn Công nghệ IoT hiện đại
NT532 dựa trên brief do người dùng cung cấp; chưa có rubric/learning outcome
chính thức để tuyên bố đối sánh đầy đủ. Trọng tâm là MQTT 3.1.1, topic/schema
versioned, session/sequence, retained Last Will, chống trùng, xử lý atomic và
evidence tái lập. Profile `remote-app-emulated` chỉ gây nhiễu có kiểm soát trước
MQTT publish; đó không phải network emulator, packet loss đo được hay phép đo
5G. Xem [kịch bản demo NT532](docs/demo-nt532.md) và
[nguồn báo cáo đồ án](deliverables/BAO-CAO-NT532-MQTT-MVP.md). Báo cáo mang
trạng thái `READY_FOR_SUBMISSION_WITH_DECLARED_LIMITATIONS`: bìa và thông tin
hành chính Nhóm 3 đã được điền theo mẫu tham chiếu do người dùng cung cấp, còn
các giới hạn kỹ thuật được giữ công khai trong report/evidence.

Evidence kỹ thuật khóa ngày 14/08/2026:

- implementation hiện đã được commit tại
  `bba2bc745fbf83bc5ac226e2d5b665594dbe7ba0`; các trạng thái
  `worktree_uncommitted` bên dưới là provenance lịch sử của artifact đã đo trước commit;
- baseline pin tại `7030e4b30300dec65646e3091356ca00d9eaa8f5`, `commit_clean`,
  scoped RQ1 SHA-256
  `760429f9dceed614279cb6c937d111a66fb1cb63ca813ed615c7de1bbd24c280`;
  artifact hardened được sinh với `source_state=WORKTREE_UNCOMMITTED`, scoped RQ1 SHA-256
  `4bce098e63c53ab20bc7d9ab37162848504160b620c4a1a7ebba6ccfe7de5419`;
- deterministic RQ1 probe: atomic alert và old LWT đều từ baseline `0/30` lên
  hardened `30/30`; không dùng inferential CI cho repeat cùng fixture;
- source regression suite cuối `257 passed`;
- RQ2 artifact v5: 30 cặp seed, 30 message/run. `lan-baseline` có median
  scheduled observation `1,0`, p50/p95 schedule-to-API `235,0/305,525 ms`;
  `remote-app-emulated` có `0,833333` và `632,75/969,925 ms`;
- paired median delta remote trừ LAN: coverage `-0,166667`, p50 `+363,0 ms`,
  p95 `+634,275 ms`. Attempted delivery là `1,0` ở cả hai profile nhưng chỉ là
  KPI phụ.

Aggregate nằm tại `evidence/analysis/rq2-v5-experiments.json`, SHA-256
`b2bb2e80edee83bd8a89531d079e4148ddb1442e7a9734cb2de353e4cddd4ffb`;
allowlisted source provenance tại thời điểm chạy là `worktree_uncommitted`, SHA-256
`f5e27d518f9a625397f289f90fd42bac9cf89d628c8e820a18ce55dfdacde280`.
Run chính thức dùng artifact `5.0` và prefix `nt532-rq2-v5-`. Profile
`remote-app-emulated` gây delay/jitter/drop/outage trước publish; KPI chính giữ
intentional drop trong denominator scheduled. Đây là app impairment cùng host
với `network_claim=none`, `measured_5g=false`, không phải kết quả mạng/5G.

Software E2E acceptance ngày 14/08/2026 cũng đã chạy qua Mosquitto và Edge live
không upload firmware: normal và motion artifact không tạo alert mới; motion
artifact buộc HR/SpO2 về `null` + invalid; low SpO2 hợp lệ tạo đúng một logical
alert và ACK lặp vẫn giữ trạng thái `acknowledged`. Do ACL broker giới hạn
credential `health_node` vào namespace `health-node-01`, ba lượt dùng cùng
device ID và phân biệt bằng boot ID, không nới wildcard. Exact command/seed,
snapshot API redacted và browser evidence nằm tại
[biên bản nghiệm thu phần mềm](plans/reports/260814-073149-software-e2e-acceptance/report.md).
Kết luận là **GO cho MVP phần mềm demo/chấm môn**, không phải xác minh node vật
lý, độ chính xác y tế hoặc backhaul 5G.

## Chạy nhanh nhất: simulator trước, chưa cần cắm mạch

Yêu cầu: Docker Desktop đang chạy. Python 3.11+ chỉ cần cho simulator hoặc khi
chọn chạy edge trực tiếp. Để chạy local, test, artifact runner và browser smoke,
cài dependency khóa của project:

```powershell
python -m pip install -e ".[test,artifact]"
pnpm install --frozen-lockfile
```

Sau đó tạo tài khoản broker:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\scripts\Initialize-Mosquitto.ps1
```

Script hỏi hai mật khẩu khác nhau: một cho `health_edge`, một cho `health_node`.
Không đưa chúng vào Git, ảnh chụp màn hình hoặc cuộc trò chuyện.

### Phương án A — Docker đầy đủ

Sao chép cấu hình mẫu một lần, rồi thay `MQTT_PASSWORD` bằng mật khẩu
`health_edge` vừa tạo. `.env` đã bị Git bỏ qua nhưng vẫn chứa bí mật cục bộ:

```powershell
if (-not (Test-Path -LiteralPath .\.env)) {
    Copy-Item -LiteralPath .\.env.example -Destination .\.env
}
notepad .\.env
docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full up -d --build
docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full ps
```

Profile `full` chạy cả Mosquitto và edge/dashboard. API chỉ được publish ra
`127.0.0.1:8000`; SQLite nằm trong Docker volume `edge-data`.

### Phương án B — broker Docker, edge chạy trực tiếp

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test,artifact]"
docker compose -f .\deploy\docker-compose.yml up -d
$env:MQTT_USERNAME = 'health_edge'
$env:MQTT_PASSWORD = '<mat-khau-edge-vua-tao>'
$env:EDGE_DATABASE_PATH = '.\data\health-edge.db'
python -m uvicorn edge.app:app --host 127.0.0.1 --port 8000
```

Không chạy đồng thời edge Docker và edge trực tiếp trên cùng cổng 8000.

Để phát dữ liệu tổng hợp, mở PowerShell khác và chuẩn bị Python nếu chưa làm:

```powershell
if (-not (Test-Path .\.venv)) { py -m venv .venv }
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test,artifact]"
$env:SIMULATOR_MQTT_USERNAME = 'health_node'
$env:SIMULATOR_MQTT_PASSWORD = '<mat-khau-node-vua-tao>'
python -m simulator --scenario normal --count 20
```

Mở `http://127.0.0.1:8000`. Các kịch bản có sẵn:

```powershell
python -m simulator --scenario motion_artifact --count 20
python -m simulator --scenario ds18b20_fault --count 20
python -m simulator --scenario low_spo2 --count 20
python -m simulator --scenario high_hr --count 20
python -m simulator --scenario fall --count 8
python -m simulator --scenario offline --count 5
```

Muốn xem payload mà chưa chạy broker:

```powershell
python -m simulator --scenario fall --count 4 --dry-run
```

## Thông báo Telegram tùy chọn

Edge có thể gửi một tin tiếng Việt khi alert ngưỡng mới mở và cho mỗi sự kiện
ngã demo mới đã chống trùng. Tính năng bị tắt mặc định; lỗi Telegram không làm
dừng MQTT, SQLite hoặc dashboard.

Bot token và Chat ID chỉ được điền vào `.env` cục bộ, không đưa vào mã nguồn,
ảnh chụp hoặc cuộc trò chuyện. Xem [hướng dẫn Telegram](docs/telegram-notifications.md)
để tạo bot, lấy Chat ID, bật Docker và chạy bài thử. Đây là kênh best-effort
phi lâm sàng, không phải hệ thống cấp cứu.

## Chuyển sang phần cứng

1. Đấu dây theo [BOM và wiring](docs/bom-and-wiring.md).
2. Bật hotspot/router ở Wi-Fi 2,4 GHz (ESP8266 không hỗ trợ Wi-Fi 5 GHz),
   khởi tạo broker như trên và tìm IPv4 của laptop bằng `ipconfig`.
3. Cho phép TCP 1883 trên Windows Firewall **chỉ với mạng Private**.
4. Điền Wi-Fi, IPv4 broker hiện tại và tài khoản node vào
   `firmware/health-node/include/secrets.h`. Nếu dùng broker trên laptop, có thể
   chạy `START-IOT-HEALTH-EDGE.bat`; launcher sẽ dừng trước khi nạp nếu
   `MQTT_HOST` không khớp một IPv4 cục bộ đang hoạt động.
5. Xem Serial Monitor trước, sau đó kiểm tra dashboard và [checklist](docs/test-checklist.md).

Linh kiện cốt lõi người dùng đã có đủ. Breadboard, dây Dupont, cáp USB data và
nguồn ổn định chỉ là vật tư hỗ trợ lắp thử. DS18B20 dùng chế độ cấp nguồn ba dây:
VDD lên 3V3, GND chung, DATA tại D5/GPIO14 và điện trở **4,7 kΩ** từ DATA lên
3V3. Firmware `0.3.1` bật thêm pull-up nội yếu của ESP8266 như một fallback cho
dây prototype ngắn; fallback này không thay thế điện trở ngoài. Bản wearable ổn
định vẫn bắt buộc có pull-up 4,7 kΩ đúng tại DATA lên 3V3. Không dùng
parasite-power trong cấu hình này. Buzzer/nút nhấn là tùy chọn; thao tác ACK
chính nằm trên dashboard.

Source firmware `0.3.1` phát strict `health.telemetry.v3` với
`wearable.wrist_surface_temp_c` và `quality.wrist_surface_temp_valid`. Phép
chuyển đổi DS18B20 12-bit được yêu cầu bất đồng bộ rồi đọc sau ít nhất `750 ms`;
vòng lặp không chờ bằng `delay()`. Edge tiếp tục xác thực v1/v2 và giữ nguyên
dữ liệu `skin_temp_*`, môi trường DHT11 cùng raw payload lịch sử trong SQLite;
không giá trị legacy nào bị đổi nghĩa thành nhiệt độ cổ tay. Firmware nhận
MPU-6050 có `WHO_AM_I=0x68` hoặc module
MPU-6500-compatible có `WHO_AM_I=0x70`, cùng ở địa chỉ I2C `0x68`. Mã lỗi công
khai cũ `mpu6050_unavailable` được giữ lại cho cả hai biến thể để không phá vỡ
edge/dashboard. Xem chi tiết trong [hợp đồng dữ liệu](docs/data-contract.md).

Firmware `0.2.2` đã sửa và được kiểm tra trên phần cứng cho đường khôi phục FIFO
MAX30102: không dùng giá trị
`OVF_COUNTER` đọc trước mẫu làm gate, vì counter bão hòa sau overflow lúc khởi
động có thể giữ node trong vòng clear-and-return. Cửa sổ PPG vẫn fail-closed khi
khoảng lấy mẫu vượt `250 ms` hoặc `check()` của thư viện SparkFun trả về từ bốn
mẫu trong buffer cục bộ. Phiên `0.2.2` đã có raw quang học và 20 telemetry
production liên tiếp với HR/SpO₂ hợp lệ khi đặt ngón tay ổn định; đây chỉ là
bring-up phi lâm sàng, không chứng minh độ chính xác y tế. Source `0.3.1` giữ
nguyên đường MAX/dual-MPU này và đã được upload trong phiên bring-up ngày
2026-08-14. Sau khi rollback driver CH340 từ `3.9.2024.9` xuống `3.7.2022.1`,
scanner A/B không thấy ROM ở nhánh `external_only`, nhưng nhánh có fallback
pull-up nội tìm được family `0x28`, CRC hợp lệ, nguồn addressed ở chế độ powered
và nhiệt độ `27.3125 °C`. Sau hard reset, Serial của production boot
`a164b119f1fd90b3` báo firmware `0.3.1`, Wi-Fi tại `192.168.137.37` và MQTT đã
kết nối. Telemetry mới tại `seq=23/25/28` có nhiệt độ cổ tay `27.3125 °C`, cờ
hợp lệ, motion hợp lệ/`idle` và `sensor_faults=[]` ở cả ba mẫu. MAX30102 không
còn fault unavailable hoặc `ppg_sample_loss`; do chưa đặt ngón tay,
`finger_present=false` và HR/SpO₂ là `null` đúng fail-closed, nên vẫn chưa phải
bằng chứng HR/SpO₂ mới. Dashboard hiển thị node online, nhiệt độ `27.3 °C` hợp
lệ, firmware `0.3.1` và không có lỗi trình duyệt.

Đoạn trên là nhật ký bring-up lịch sử, không phải physical-node gate của batch
validation báo cáo hiện tại. Batch cuối không upload và không chạy lại node;
vì vậy biên bản NT532 vẫn ghi **physical node demo = `NOT_VERIFIED`**. Khi trình
bày phần cứng, phải thu evidence mới theo `docs/demo-nt532.md` thay vì tái dùng
ảnh/runtime cũ.

## Lưu ý về 5G

Nếu NodeMCU và laptop cùng là hai máy ngang hàng trên hotspot điện thoại, MQTT tới broker trên laptop thường chỉ đi trong WLAN cục bộ. Đây là **demo LAN**, không đủ bằng chứng để tuyên bố dữ liệu đã qua 5G.

“5G” ở đây là mạng di động thế hệ 5, không phải băng tần Wi-Fi 5 GHz.

Chỉ gọi là thử nghiệm backhaul 5G khi broker/edge nằm ở đầu xa và tuyến dữ liệu thực sự đi qua Internet 5G, kèm bằng chứng cấu hình/tuyến/độ trễ. Xem [chế độ mạng và bảo mật](docs/network-and-security.md).

Firmware dùng PubSubClient nên một lần kết nối lại MQTT có thể tạm ngắt lấy mẫu
chuyển động khoảng hai giây. Cửa sổ PPG/candidate ngã sẽ bị hủy an toàn sau
khoảng trống, nhưng sự kiện nằm trọn trong khoảng đó có thể bị bỏ lỡ. Đây là
giới hạn đã chấp nhận của MVP phi lâm sàng, không phải cơ chế an toàn cá nhân.

## Tài liệu

- [Kiến trúc và ranh giới](docs/architecture-and-scope.md)
- [BOM và wiring](docs/bom-and-wiring.md)
- [Quickstart Windows](docs/windows-quickstart.md)
- [Hợp đồng dữ liệu MQTT](docs/data-contract.md)
- [Chế độ mạng và bảo mật](docs/network-and-security.md)
- [Khắc phục sự cố](docs/troubleshooting.md)
- [Checklist kiểm thử](docs/test-checklist.md)
- [Kịch bản demo NT532 IoT Protocol](docs/demo-nt532.md)
- [Nguồn báo cáo NT532 MQTT MVP](deliverables/BAO-CAO-NT532-MQTT-MVP.md)
- [Thông báo Telegram](docs/telegram-notifications.md)
- [Nhật ký bring-up DS18B20 2026-08-14](docs/journals/2026-08-14-ds18b20-hardware-bringup.md)

## Cấu trúc

```text
firmware/   firmware PlatformIO cho NodeMCU
edge/       MQTT ingestion, SQLite, FastAPI và dashboard
simulator/  bộ phát dữ liệu MQTT tổng hợp
deploy/     Mosquitto, profile edge Docker, ACL và generator mật khẩu
docs/       hướng dẫn vận hành và kiểm thử
tests/      kiểm thử tự động
```
