# Tổng Quan Kiến Trúc & Case Study Chi Tiết: Android Agentic SDLC (`android-agentic-sdlc`)

## 1. Mở Đầu

Khi các trợ lý AI phát triển phần mềm tiến hóa từ việc gợi ý code đơn thuần sang các Agent tự chủ thực hiện chuỗi tác vụ phức tạp, các đội ngũ phát triển ứng dụng di động gặp phải những rào cản vận hành rất đặc thù. Nếu không có các quy chuẩn miền nghiêm ngặt, các mô hình ngôn ngữ lớn (LLM) thường gặp khó khăn với vòng đời (lifecycle) phức tạp của Android, tự ý sinh ra các lớp trừu tượng thừa thãi, sửa lan man sang các file lân cận và đẩy code lên mà không qua kiểm chứng thực tế.

Để đạt **tính thực dụng tối đa** và loại bỏ chi phí đọc file thừa (tool-call overhead), repository này kết hợp chặt chẽ 3 tầng bảo vệ: **Quy tắc nền luôn bật (Always-On Rule)**, **Chốt chặn cơ học 0-Token (PreToolUse Hook)**, và **Các kỹ năng tác vụ chuyên biệt (Agent Skills)**:

- **1 Quy Tắc Nền Luôn Bật (`rules/code-hygiene.md`)**: Tự động áp dụng thiết kế SOLID tinh gọn (trước khi code), chuẩn comment "Why-only" (trong khi code), và dọn rác YAGNI (sau khi code) trên mọi dòng code mà không cần gọi lệnh.
- **1 Chốt Chặn Hook Cơ Học (`hooks/hooks.json` & `hooks/scripts/pre-tool-guard.py`)**: Chạy dưới 20ms với chi phí 0 token trước khi AI ghi file hoặc chạy lệnh bash, chặn cứng 100% hành vi `import android.*` trong `/domain/`, viết Maestro YAML sai chuẩn (`point:` hoặc thiếu assert), và gọi `maestro test` thô gây tràn token.
- **9 Agent Skills Chuyên Biệt (`skills/`)** chuẩn hóa theo các pha của vòng đời phát triển phần mềm (SDLC):
  - **`plan-*`**: Chuẩn hóa yêu cầu & Lập kế hoạch kiến trúc (`plan-feature`, `plan-slicing`).
  - **`code-*`**: Bóc tách tầng nghiệp vụ thuần Kotlin (`code-domain`).
  - **`guard-*`**: Kiểm soát bán kính rủi ro & khóa vành đai an toàn (`guard-blast`).
  - **`test-*`**: Điều tra lỗi, soạn thảo kịch bản & chạy test trên thiết bị (`test-hunter`, `test-author`, `test-runner`).
  - **`flow-*`**: Nhạc trưởng điều phối tự động hóa khép kín (`flow-bug`).
  - **`ship-*`**: Kiểm toán diff & xuất xưởng Merge Request (`ship-mr`).

---

## 2. Tại Sao Gộp 3 Skill Mỏng Thành 1 Quy Tắc Luôn Bật (`rules/code-hygiene.md`)?

### `rules/code-hygiene.md` — Thiết Kế Tinh Gọn (Lean SOLID) · Chú Thích Ý Đồ (Why-Only) · Dọn Rác (YAGNI Simplify)
- **Nỗi đau thực tế:** Ở các phiên bản đầu, việc kiểm soát chất lượng code bị tách làm 3 skill rời (`code-solid`, `code-doc`, `code-simplify`). Trong thực tế làm việc hàng ngày, không lập trình viên nào gõ 3 lệnh slash command liên tiếp chỉ để viết một đoạn code sạch, và các luồng tự động phải tốn thêm 2–3 lượt gọi `read_file` chỉ để nạp các checklist ngắn.
- **Tại sao tiến hóa thành Always-On Rule:** Chất lượng code là **bất biến (invariant)**, không phải một bước tùy chọn. Mọi dòng code AI viết ra đều phải mặc định chống over-engineering, không có comment rác và tự làm phẳng logic trước khi trả kết quả.
- **Giải pháp & Giá trị:** Hợp nhất trọn vẹn 3 chốt chặn vào một file Rule 45 dòng luôn kích hoạt:
  1. **Trước khi code (Lean SOLID):** Phản biện các lớp trừu tượng thừa (*"Interface này có thực sự có từ 2 implementation trở lên không?"*).
  2. **Trong khi code (Why-Only Docs):** Cấm tuyệt đối comment dịch lại cú pháp code; bắt buộc mọi mệnh đề nhân quả trong comment phải được đối chiếu với dòng code thực tế.
  3. **Sau khi code (YAGNI Simplify):** Làm phẳng `if/else` bằng early return, xóa sạch `Log.d` tạm, và cấm mở `public` chỉ để phục vụ unit test.

---

## 3. Case Study Chi Tiết Từng Kỹ Năng (9 Core Skills)

### 3.1. `plan-feature` — Chuẩn Hóa Yêu Cầu và Xóa Bỏ Sự Mơ Hồ
- **Nỗi đau thực tế:** Yêu cầu tính năng thường nằm rải rác ở nhiều nguồn: mô tả Jira sơ sài, link Figma chưa chốt, và thảo luận rải rác trên Slack. Khi yêu cầu AI "hãy code tính năng này", nó thường bắt tay vào gõ code ngay dựa trên những giả định chưa được kiểm chứng, hoặc đẻ ra 4–5 file kế hoạch phân mảnh gây quá tải nhận thức.
- **Tại sao skill ra đời:** Áp dụng kiến trúc lập kế hoạch tinh gọn trong 1 file duy nhất (`plans/<EPIC>/PLAN.md`).
- **Giải pháp & Giá trị:** Đối soát các nguồn tài liệu ngay từ đầu, liệt kê câu hỏi tự thân kèm mẫu tin nhắn Slack (Persona-Aware) để copy-paste hỏi PM/BE trong 3 giây, tập trung 100% vào **Tam giác bất thường (Anomaly Triangle)** thay vì viết văn mô tả Happy Path.

### 3.2. `plan-slicing` — Triệt Tiêu MR Khổng Lồ & Chống Hallucination Nhờ Quy Hoạch Cuốn Chiếu 3 Tầng (JIT)
- **Nỗi đau thực tế:** Khi giao một Epic lớn cho AI, có 2 cái bẫy chết người: (1) AI đẻ ra một Pull Request khổng lồ hàng nghìn dòng code không thể review, hoặc (2) bắt AI trong 1 phiên phải quét toàn bộ codebase và lập kế hoạch chi tiết cho cả 4–5 Slices (20+ steps) cùng lúc, khiến AI bị loãng sự chú ý và sinh ra **hallucination** (bịa tên hàm, râu ông nọ cắm cằm bà kia).
- **Tại sao skill ra đời:** Để bẻ khóa các tính năng phức tạp theo cơ chế **Quy hoạch cuốn chiếu 3 tầng (3-Tier Just-In-Time Progressive Planning)** tách biệt qua từng session sạch (`init <EPIC>` $\to$ `plan <slice-id>` $\to$ `step <slice-id> <step-id>`).
- **Giải pháp & Giá trị:**
  1. **Tầng 1 (`init <EPIC>` — Session của Lead):** Tạo `CONTRACT.md` khóa chặt interface/mock dùng chung và lập bảng tổng quan các Slices trong `PLAN.md §4` (`NOT PLANNED`), sau đó xóa ngữ cảnh (`/clear`).
  2. **Tầng 2 (`plan <slice-id>` — Session của người nhận Slice):** Ai nhận Slice nào mới mở session riêng chạy `plan` cho **đúng 1 Slice đó** (ví dụ `slice-01`), chia ra khung 3–5 bước (`step-01..step-05`: chỉ gồm Mục tiêu + Tiêu chí nghiệm thu AC), sau đó `/clear`.
  3. **Tầng 3 (`step <slice-id> <step-id>` — Mỗi Step 1 Session Riêng = 1 MR):** Khi bắt tay vào làm Step nào (ví dụ `step-01`), dev mở một session mới tinh. Lúc này AI mới quét các file code liên quan đến `step-01`, tự lên micro-plan chi tiết và code gọn trong $\le 300$ dòng/MR.
  4. **Hấp thụ thay đổi giữa chừng (`delta <EPIC>` — Giao thức 2 Nhịp Bảo Vệ Sự Tập Trung):** Khi PRD, Figma hoặc BE thay đổi giữa sprint, nếu không va chạm trực diện với step đang `IN PROGRESS`, hệ thống chỉ cất vào hàng chờ trong `PLAN.md §2` (**0 Context Switch**), đợi tới khi dev xong step hiện tại và gõ `/clear` mới kích hoạt `guard-blast` Mode 1 (`Plan → Execute → Regression`).

### 3.3. `code-domain` — Cô Lập Nghiệp Vụ Khỏi Code Legacy & Ngăn Chặn Hallucination
- **Nỗi đau thực tế:** Trong các codebase Android cũ, các "God Activity" hay ViewModel dài hơn 1.500 dòng thường trộn lẫn truy vấn DB, lời gọi Android SDK (`Context`, `SharedPreferences`) và quy tắc nghiệp vụ cốt lõi. Khi AI sửa các class này, nó rất dễ bị hallucination hoặc làm gãy vòng đời Android.
- **Tại sao skill ra đời:** Cô lập hoàn toàn các quy tắc nghiệp vụ thuần túy ra khỏi kiến trúc cũ thành một tầng pure Kotlin domain — nhưng **biết khuyên bỏ qua (Skip Layer)** nếu chỉ là CRUD đơn giản.
- **Giải pháp & Sự tiến hóa:** Bóc tách logic thành các Entities, UseCases và Sealed Class Errors thuần Kotlin sau khi đi qua cổng duyệt **Approval Gate**. Skill này cung cấp hợp đồng nghiệp vụ chuẩn cho `plan-slicing`, khoanh vùng phạm vi cho `guard-blast`, và định hình kịch bản test cho `test-author`.

### 3.4. `test-hunter` — Kỹ Sư Điều Tra Nguyên Nhân Gốc (Chỉ Đọc — Không Sửa Code)
- **Nỗi đau thực tế:** Khi nhận một báo cáo lỗi hay stack trace, phần lớn AI agent lập tức nhảy vào sửa code dựa trên suy đoán bề mặt, làm bẩn lịch sử git và đẻ ra lỗi mới.
- **Tại sao skill ra đời:** Tách bạch tuyệt đối giữa hai giai đoạn: *Chẩn đoán (Diagnosis)* và *Thực thi sửa lỗi (Implementation)*.
- **Giải pháp & Giá trị:** Hoạt động ở chế độ chỉ đọc (read-only). Agent điều tra qua ticket Jira, stack trace, mã nguồn và xuất ra báo cáo `DIAGNOSIS` rõ ràng: cơ chế gây lỗi, điều kiện kích hoạt, và danh sách chính xác các file liên quan mà không chạm vào một dòng code nào.

### 3.5. `guard-blast` — Kiểm Soát Phạm Vi Ảnh Hưởng & Chống Lỗi Hồi Quy
- **Nỗi đau thực tế:** Khi sửa một lỗi nhỏ hoặc cập nhật thay đổi thiết kế giữa chừng, AI thường sửa lan sang các file không liên quan, dẫn đến lỗi hồi quy ngầm (regressions).
- **Tại sao skill ra đời:** Thiết lập vành đai bảo vệ nghiêm ngặt xung quanh các thay đổi của hệ thống.
- **Giải pháp & Giá trị:** Hoạt động ở 2 chế độ:
  - *Chế độ 1 (Thay đổi spec/thiết kế/BE — Triage 2 Nhịp Focus-First):* Bảo vệ sự tập trung khi đang code dở step bằng cách cất các thay đổi không va chạm vào hàng đợi (Nhịp 1); chỉ khi sang ranh giới `/clear` (Nhịp 2) mới đánh giá độ phức tạp (`Level 1` sửa trực tiếp step TODO, `Level 2` chèn step mới vào cuối Slice, `Level 3` nâng cấp `CONTRACT.md`), rà soát lại các phần đã `DONE` mà không xóa lịch sử, và lập ma trận hồi quy 3 tầng.
  - *Chế độ 2 (Phạm vi ảnh hưởng của bug):* Thiết lập danh sách cho phép (**Allowlist**) nghiêm ngặt cho các file được sửa (đối chiếu bằng `git diff --name-only`) và trích xuất ma trận test hồi quy 3 cấp độ (Tier 1 $\to$ Tier 3).

### 3.6. `test-author` — Tự Động Soạn Thảo Kịch Bản Test Maestro Chuẩn Xác
- **Nỗi đau thực tế:** Tự viết test E2E cho mobile bằng tay rất mất thời gian, còn để AI tự viết tự do thì kịch bản rất dễ gãy do dùng tọa độ chạm cứng (`point:`), thiếu assertion hoặc lạm dụng `sleep`.
- **Tại sao skill ra đời:** Tự động tạo các luồng test Maestro YAML chuẩn xác, ổn định và được kiểm chứng bằng công cụ phân tích tĩnh.
- **Giải pháp & Giá trị:** Ép chuẩn cấu trúc thư mục nghiệp vụ (`01-order-list/`), đặt tên file chuẩn (`ac-01-display-all-orders.yaml`), trích xuất AC tự động qua `extract-acceptance.sh` và chặn lỗi tĩnh bằng `validate-flow.py`.

### 3.7. `test-runner` — Thực Thi Test Thiết Bị Lớn Với Giám Sát Real-Time & 0 Token Bleed
- **Nỗi đau thực tế:** Một bộ test regression thực tế có thể lên tới gần 300 kịch bản. Chạy từng kịch bản qua lệnh gọi MCP của LLM sẽ đốt hàng trăm nghìn token và làm treo phiên làm việc.
- **Tại sao skill ra đời:** Cung cấp bộ chạy test native thống nhất (`suite-runner.py`) với chi phí token bằng 0 khi test vượt qua và hiển thị tiến độ trực quan.
- **Giải pháp & Giá trị:** Cung cấp 4 preset (`-m repro`, `step`, `regression`, `smoke`), stream dữ liệu ANSI trực tiếp ra cửa sổ Terminal riêng, tự động chụp ảnh màn hình/UI tree và tạo báo cáo lỗi khi fail, đo kích thước dp/màu sắc so với Figma qua `device.py`, và đo lường chính xác lượng token tiêu thụ qua `token-usage.py`.

### 3.8. `flow-bug` — Nhạc Trưởng Điều Phối Toàn Diện Vòng Đời Bug
- **Nỗi đau thực tế:** Quy trình sửa bug truyền thống bị phân mảnh giữa đọc log, chạy máy ảo, sửa code trong IDE và viết PR, làm rơi rụng ngữ cảnh.
- **Tại sao skill ra đời:** Một lệnh duy nhất tự động hóa toàn bộ vòng đời của lỗi (Hiểu $\to$ Sửa $\to$ Chứng minh $\to$ Xuất xưởng).
- **Giải pháp & Giá trị:** Điều phối liên hoàn 5 kỹ năng (`test-hunter` $\to$ `guard-blast` $\to$ `test-author` $\to$ `test-runner` $\to$ `ship-mr`) dưới sự giám sát của `rules/code-hygiene.md` thông qua file trạng thái `plans/<TICKET>/flow-bug.md`, bắt buộc kiểm chứng Negative Control và chỉ yêu cầu kỹ sư duyệt ở đúng 3 cổng.

### 3.9. `ship-mr` — Kiểm Toán Diff & Soạn Thảo Merge Request Kèm Bằng Chứng
- **Nỗi đau thực tế:** Lập trình viên và AI thường viết mô tả PR sơ sài mà không đối soát kỹ git diff với yêu cầu thực tế, thậm chí viết những nhận định suy đoán sai sự thật vào commit/comment.
- **Tại sao skill ra đời:** Đảm bảo mọi Merge Request đều được kiểm toán đối chiếu chặt chẽ (bao gồm **Claim Check**) và có đầy đủ bằng chứng kiểm thử trước khi bàn giao.
- **Giải pháp & Giá trị:** Kiểm toán ngân sách diff ($\le 300$ dòng), xác minh mọi mệnh đề nhân quả trong comment/commit, kiểm tra việc tuân thủ Allowlist, tạo commit chuẩn Conventional Commits và soạn thảo nội dung MR đính kèm bằng chứng test thực tế.

---

## 4. Bước Tiến Hóa Hợp Lực Giữa Rule & Skills

Sức mạnh thực sự xuất hiện khi **1 Core Rule** và **9 Core Skills** vận hành cùng nhau:
- `rules/code-hygiene.md` đóng vai trò "ý thức kỷ luật tự động" giữ cho mọi dòng code sinh ra luôn tinh gọn, đúng chuẩn SOLID thực chiến và không có comment rác.
- Khi nghiệp vụ đã được `code-domain` cô lập thành UseCase sạch, `guard-blast` tính toán chính xác phạm vi ảnh hưởng, `plan-slicing` định hình hợp đồng mock chuẩn xác, và bộ đôi `test-author` + `test-runner` chứng minh chất lượng trên thiết bị thật mà không lãng phí token.
