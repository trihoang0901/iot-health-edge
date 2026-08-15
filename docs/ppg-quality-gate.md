# Cổng chất lượng PPG và quy trình hiệu chỉnh

Đây là cơ chế fail-closed cho prototype phi lâm sàng. Nó giảm việc công bố số
sai; không chứng minh MAX30102 đạt độ chính xác y tế.

## Luồng xác nhận

Mỗi cửa sổ 100 mẫu (xấp xỉ 4 giây ở 25 mẫu/giây) đi qua các bước sau:

1. Bác cửa sổ khi chưa có ngón tay, mất mẫu hoặc thiếu dữ liệu chuyển động.
2. Bác khi có motion artifact, ít nhất 3 mẫu quang chạm biên ADC, hoặc biên độ
   AC/DC của IR dưới 0,3%; IR median dưới 10.000 hoặc Red median dưới 5.000
   cũng được coi là tín hiệu quang yếu.
3. Tìm các đỉnh IR và kiểm tra khoảng RR bằng median/MAD. MAD tương đối phải
   không quá 15%; BPM từ RR phải cách ứng viên MAXIM không quá 12 bpm.
4. Đưa ứng viên đạt gate vào cửa sổ 5 kết quả. Hampel dùng median và MAD để
   loại outlier; cần ít nhất 3 kết quả nhất quán và độ trải không quá 12 bpm.
   SpO₂ cũng có Hampel riêng và độ trải tối đa 4 điểm phần trăm; SpO₂ bất ổn
   không được phép biến thành confirmed thấp giả.
5. Sau khi đã có mốc confirmed, ứng viên lệch trên 25 bpm làm confirmed thành
   `null`. Mức mới chỉ được công bố sau 3 cửa sổ cùng xác nhận.

Không có bước giữ giá trị cũ hoặc EMA. Khi gate không chắc chắn, firmware phát
raw candidate để audit (nếu có), nhưng confirmed là `null` cùng một reason:
`no_finger`, `warming_up`, `motion`, `clipping`, `low_perfusion`, `unstable`
hoặc `sample_loss`.

Các ngưỡng trên là giá trị khởi đầu để kiểm thử, không phải ngưỡng sinh lý phổ
quát. Chỉ thay đổi sau khi có dữ liệu gắn nhãn từ đúng breakout và cách đặt cảm
biến của đồ án.

Gate còn giới hạn ứng viên HR trong `40..220 bpm` và SpO₂ trong `50..100%`.
Đây là engineering bounds để loại output thuật toán vô lý, không phải chuẩn
lâm sàng. Cửa sổ 100 mẫu là rolling và được đánh giá tối đa mỗi giây.

**Trạng thái bằng chứng:** logic mới đã qua native/synthetic tests và build
NodeMCU, nhưng chưa upload và chưa có capture `0.4.0` finger-present. Vì vậy
độ ổn định quang học/HR/SpO₂ vật lý hiện là **`NOT_VERIFIED`**.

## Cơ khí và quang học

- Dùng kẹp ngón tay giữ sensor phẳng, không trượt; thêm cao su/foam mềm để lực
  ép lặp lại được nhưng không ép chặt làm giảm tưới máu.
- Làm vách tối quanh LED/photodiode và vỏ che ánh sáng ngoài. Không để LED đỏ
  rọi trực tiếp sang photodiode qua nhựa trong.
- Giữ tay và dây dẫn cố định trong lúc xác nhận. Với chiến lược hiện tại, IMU
  báo chuyển động thì hệ thống chủ động không đo thay vì đoán BPM.
- Dùng ngón tay cho MAX30102 red/IR. Không suy diễn kết quả này thành khả năng
  đo liên tục ở cổ tay khi vận động.

## Thu dữ liệu để chỉnh LED và ADC

Không chỉnh LED/ADC chỉ từ BPM hiển thị. Với từng cấu hình, ghi đồng bộ raw
Red/IR và IMU trong ít nhất các pha: không có ngón tay, đặt ngón ổn định, đổi
nhẹ lực kẹp, che/mở ánh sáng, rung tay, nghỉ và sau vận động.

Repo hiện không có logger production cho raw Red/IR + IMU; test contract còn
cố ý ngăn diagnostic path lọt vào firmware bàn giao. Trước khi chạy ma trận
này cần tạo một diagnostic sketch/tool riêng, không mang credential production,
và lưu artifact capture có timestamp/cấu hình. Chưa có artifact thì bước hiệu
chỉnh phải giữ trạng thái **`NOT_VERIFIED`**.

Theo dõi cho mỗi cửa sổ:

- median, P10/P90 và số mẫu chạm biên của Red/IR;
- AC/DC, RR median, RR MAD và reason bị bác;
- raw candidate, confirmed value và thời gian chờ xác nhận;
- coverage (tỷ lệ cửa sổ có confirmed), false-valid, false-jump, MAE và p95
  error so với ECG/chest strap tham chiếu.

Giảm LED current hoặc tăng ADC range nếu có clipping; tăng LED current từng
bước nhỏ nếu DC quá thấp và không clipping. Mục tiêu là đưa Red/IR vào vùng
động ổn định với phần AC còn nhìn rõ, không tối đa hóa trị số raw. Sau mỗi thay
đổi phải chạy lại toàn bộ ma trận trên nhiều lần đặt ngón.

Nếu mục tiêu đổi thành đo cổ tay liên tục khi đang vận động, cần dữ liệu PPG và
accelerometer đồng bộ để bù nhiễu hoặc sensor-hub/cảm biến có thuật toán motion
compensation. Bộ gate hiện tại cố ý abstain khi chuyển động.
