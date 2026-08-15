# Chế độ mạng và bảo mật

## Phân loại đúng chế độ mạng

### A. Laptop và NodeMCU cùng hotspot/router

```text
NodeMCU --Wi-Fi--> hotspot/router --LAN--> broker trên laptop
```

Đây là chế độ bring-up tốt nhất. Nếu hai thiết bị là peer cùng WLAN, gói MQTT có thể được chuyển nội bộ và không đi qua mạng di động, dù điện thoại hiện biểu tượng 5G. Báo cáo phải gọi đây là **demo LAN qua hotspot**, không tuyên bố đã đo backhaul 5G.

NodeMCU ESP8266 chỉ dùng Wi-Fi **2,4 GHz**. Hãy đặt băng tần hotspot/router
thành 2,4 GHz và dùng chế độ bảo mật tương thích WPA2 nếu chế độ WPA3-only
không kết nối được. “5G” trong tài liệu này là mạng di động thế hệ 5, hoàn toàn
khác với băng tần Wi-Fi “5 GHz”.

Một số điện thoại bật client isolation, làm NodeMCU không truy cập được laptop. Khi đó dùng router cho phép peer-to-peer hoặc chế độ USB tether + Mobile Hotspot dưới đây.

### B. Broker/edge ở đầu xa

```text
NodeMCU -> hotspot 5G -> Internet -> broker/edge từ xa
```

Chỉ chế độ này mới phù hợp để đo backhaul 5G, với điều kiện có bằng chứng tuyến dữ liệu và broker thực sự ở mạng khác. Ghi lại nhà mạng/chế độ mạng, IP/đầu cuối, thời gian thử, RTT và mất gói; so sánh cùng một tải với baseline Wi-Fi nếu nghiên cứu hiệu năng.

Docker Compose trong repo chỉ mở MQTT plaintext 1883 cho LAN. Không đưa cấu hình đó lên VPS hoặc forward cổng từ Internet. Trong MVP hiện tại, nếu chưa kiểm chứng TLS và CA trên cả firmware lẫn edge, hãy đặt broker từ xa sau VPN/private overlay do nhóm kiểm soát. Không tuyên bố “MQTT an toàn qua TLS” chỉ vì đã bật một cờ ở một phía.

### C. USB tether điện thoại → laptop → Windows Mobile Hotspot

```text
Internet 5G -> USB tether -> laptop
                               \-> Windows Mobile Hotspot -> NodeMCU
```

Windows thường đặt IP laptop ở adapter Mobile Hotspot là `192.168.137.1`, nhưng đây không phải cam kết; luôn kiểm tra `ipconfig`. Firmware dùng IP thực tế đó làm broker local.

Nếu broker vẫn chạy trên laptop, MQTT từ NodeMCU tới laptop vẫn là lưu lượng cục bộ và chưa chứng minh qua 5G. Chỉ lưu lượng từ NodeMCU/laptop tới broker đầu xa mới đi tiếp qua USB tether 5G.

## Profile thí nghiệm và ranh giới tuyên bố 5G

Hai profile của experiment runner đều là profile ở **tầng ứng dụng**:

- `lan-baseline`: không chủ động thêm trễ hoặc bỏ logical message;
- `remote-app-emulated`: lập lịch delay/jitter/drop/outage trước MQTT publish,
  luôn mang `profile_kind=app_impairment`, `injection_point=before_mqtt_publish`
  và `network_claim=none`.

Vì điểm chèn nằm trước MQTT publish, `intentionally_dropped` chỉ là bản tin mà
runner chủ động không attempt. Không được đổi tên nó thành packet loss, không
dùng nó để suy luận TCP retransmission/MQTT reconnect và không coi profile là
benchmark Wi-Fi, nhà mạng hoặc 5G.

Contract chính thức RQ2 là artifact version `5.0`, prefix
`nt532-rq2-v5-`. Aggregate
`evidence/analysis/rq2-v5-experiments.json` có SHA-256
`b2bb2e80edee83bd8a89531d079e4148ddb1442e7a9734cb2de353e4cddd4ffb`,
30 cặp seed và 30 message/run. Source provenance tại thời điểm đo là
`source_state=worktree_uncommitted`, allowlisted SHA-256
`f5e27d518f9a625397f289f90fd42bac9cf89d628c8e820a18ce55dfdacde280`;
đây không phải hash toàn repository. Source cùng byte hiện được khóa tại commit
`935c393e03a68465e538f624ff3405cd4560eb49`.

KPI coverage chính là
`scheduled_observation_ratio = unique_api_observed / scheduled`, nên logical
drop trước publish vẫn nằm trong mẫu số. Median của `lan-baseline` là `1,0`
[1,0; 1,0], còn `remote-app-emulated` là `0,833333`
[0,8; 0,866667]. Intentional-drop ratio của remote là `0,166667`
[0,133333; 0,2]. `attempted_delivery_ratio` có median `1,0` ở cả hai profile
nhưng chỉ là KPI phụ cho message đã attempt, không được dùng để che coverage của
toàn lịch.

KPI latency chính là schedule-to-API polling upper-bound. P50/p95 median của LAN
là `235,0` [234,0; 254,087] và `305,525 ms` [289,8; 348,4]; remote là
`632,75` [539,0; 710,75] và `969,925 ms` [885,575; 1.101,75]. Paired delta
remote trừ LAN là `+363,0 ms` [+316,5; +472,25] cho p50 và `+634,275 ms`
[+564,875; +760,025] cho p95; coverage delta là `-0,166667`
[-0,2; -0,133333]. Vì dropped message không có latency, percentile chỉ áp dụng
cho message được quan sát và phải đọc cùng coverage. Measurement boundary là
`clock_domain=host_monotonic_same_process`, polling `100 ms`, app impairment
trước publish, `network_claim=none`, `measured_5g=false`. Publish-to-API chỉ là
diagnostic upper-bound. Không số nào ở đây là one-way network latency; node vật
lý chưa đồng bộ đồng hồ chỉ phù hợp với ingest-to-decision hoặc RTT
request/response.

5G chỉ là roadmap sau MVP. Chỉ mở phép đo backhaul 5G khi có broker/edge đầu xa,
bằng chứng endpoint và route/network mode, thời điểm thử, baseline cùng tải,
phương pháp đồng hồ/measurement point và transport đã bảo vệ. Tổng quan 5GS của
3GPP mô tả UE, NG-RAN và 5GC; việc điện thoại hiện biểu tượng 5G không tự chứng
minh MQTT local đã đi qua các lớp này. [RFC 9341](https://www.rfc-editor.org/rfc/rfc9341.html)
minh họa rằng phép đo loss/delay thực cần correlation tại các measurement point,
đồng bộ phù hợp và controlled domain; dự án không tuyên bố đã triển khai phương
pháp Alternate-Marking của RFC này.

## Kiểm tra reachability

1. Xác định đúng adapter và IPv4 bằng `ipconfig`.
2. Broker phải nghe `0.0.0.0:1883`; Docker map cổng `1883:1883`.
3. Windows network profile nên là Private.
4. Chỉ mở firewall TCP 1883 cho subnet cần thiết.
5. Không dùng `localhost`/`127.0.0.1` trong firmware.
6. Sau lần flash firmware phục hồi mạng, cấu hình broker bằng hostname DNS dùng
   được trên mọi profile hoặc fallback IPv4 riêng đúng subnet. IP thay đổi không
   còn yêu cầu sửa `secrets.h` và nạp lại; bootstrap chỉ dùng khi LittleFS chưa
   có cấu hình committed.
7. Xác nhận hotspot có SSID 2,4 GHz mà ESP8266 nhìn thấy; không nhầm 5G di động với Wi-Fi 5 GHz.

Trong workflow mới, `Start` và `Verify` chấp nhận bootstrap Wi-Fi/IP đã cũ và
không có đường upload. `Flash` mới fail-closed nếu bootstrap thiếu, còn `Doctor`
kiểm tra DNS/TCP/auth/ACL runtime và chỉ báo trạng thái, không in credential.
Triển khai broker đầu xa vẫn phải đáp ứng yêu cầu TLS/VPN bên dưới.

## Mô hình bảo mật MVP

- `allow_anonymous false`.
- Tài khoản edge và node khác nhau; ACL node chỉ cho ghi device ID của chính nó.
- Mật khẩu không nằm trong Git, ảnh chụp màn hình, log hay tham số shell.
- Status retain nhưng telemetry/event không retain.
- Không đưa PII vào topic/payload.
- Port 1883 chỉ dành cho LAN tin cậy: username/password và dữ liệu vẫn đi dạng plaintext.
- Không dùng tài khoản node chung cho nhiều thiết bị ở bản triển khai thật.
- Xoay vòng tài khoản bằng generator, cập nhật edge/firmware rồi khởi động lại có kiểm soát.

## Telegram và dữ liệu đi ra bên thứ ba

Khi `TELEGRAM_ENABLED=true`, edge tạo kết nối HTTPS ra Telegram Bot API và gửi
tóm tắt gồm device ID, thông điệp alert, giá trị tham khảo nếu có và thời gian
edge. Không có raw telemetry, mật khẩu MQTT hoặc token trong nội dung tin.

Bot token tương đương quyền điều khiển bot: chỉ lưu trong `.env` cục bộ, không
đưa vào Git/log/ảnh chụp và thu hồi ngay bằng BotFather nếu bị lộ. Cấu hình
container vẫn có thể được quản trị viên máy đọc qua Docker; không chia sẻ đầu
ra `docker inspect` hoặc `docker compose config` đã resolve.

Việc bật Telegram đồng nghĩa chấp nhận chuyển tóm tắt cảnh báo tới dịch vụ bên
thứ ba. Hãy dùng device ID không chứa PII và chỉ bật khi người vận hành đồng ý.
Telegram là kênh best-effort, không phải cơ chế báo động hoặc cấp cứu bảo đảm.

## TLS và ESP8266

Kết nối Internet trực tiếp phải có mã hóa, xác minh hostname/CA và quản lý chứng chỉ. ESP8266 có RAM hạn chế; TLS có thể làm giảm heap và gây reset nếu ghép với buffer cảm biến/MQTT lớn. Vì vậy cần kiểm thử trên đúng firmware, không dùng chế độ bỏ kiểm tra chứng chỉ và không coi VPN là thay thế cho kiểm soát ACL. Nếu chưa hoàn tất bài test này, giữ broker trong LAN/VPN riêng và ghi rõ giới hạn.

## Phục hồi Wi-Fi và captive portal

Firmware mới giữ tối đa ba profile Wi-Fi và endpoint broker trong LittleFS theo
cơ chế committed/candidate. `secrets.h` chỉ là bootstrap cho lần flash đầu;
`Start` và `Verify` không được dùng giá trị Wi-Fi/IP cũ trong file đó làm gate.
Chỉ `Flash` bắt buộc bootstrap hợp lệ.

Mật khẩu AP provisioning dài 20 ký tự được launcher sinh bằng RNG mật mã. Bản
đưa vào firmware nằm trong header local bị Git bỏ qua; bản phía laptop nằm
trong `deploy/mosquitto/generated/portal-access.dpapi`, được DPAPI bảo vệ theo
user Windows. Không gửi file DPAPI/header này và không đưa secret vào argv,
stdout, stderr hay log. `ShowPortalAccess` chỉ sao chép khi người dùng chủ động
bấm nút trong WinForms.

`OpenPortal` không publish MQTT trực tiếp từ launcher. Edge phải thấy status
sống, không-retained và nonce của đúng boot trước khi chấp nhận request; command
được gửi QoS 1, `retain=false`. PUBACK không phải bằng chứng portal đã mở:
launcher tiếp tục chờ `provisioning_started` có đúng correlation ID. Khi node
đã offline khỏi Wi-Fi/MQTT, chỉ reset/power-cycle hoặc cơ chế tự mở portal cục
bộ mới có thể cứu cấu hình.

Portal chỉ dùng để quản lý profile Wi-Fi và hostname/IP broker. MQTT credential
không đi qua portal. Broker 1883 vẫn là plaintext cho LAN tin cậy; khả năng tự
phục hồi endpoint không làm thay đổi ranh giới bảo mật này.
