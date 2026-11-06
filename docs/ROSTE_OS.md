# 🐧 Roste OS — ทำไมรอสเต้ต้องมี OS ของตัวเอง

> สถานะ: **ข้อเสนอ ยังไม่เริ่มทำ** (18 ต.ค. 2569)
> เอกสารนี้ตอบคำถามเดียว: *ทำไมต้องเป็น Roste OS ไม่ใช่รันต่อบน Windows แบบเดิม*
> ทุกเหตุผลอ้างไฟล์ในโปรเจกต์ไว้ — ข้อไหนยังไม่ได้วัดจริงจะเขียนกำกับว่า "ยังไม่ได้วัด"
> โครงสร้างระบบ (ตอนนี้ + เป้าหมายบน Roste OS) อยู่ที่ [ARCHITECTURE.md](ARCHITECTURE.md)

---

## 📌 สรุปสั้น

**Roste OS = Ubuntu 26.04 LTS ที่ปรับให้เป็นเครื่องของรอสเต้โดยเฉพาะ** ไม่ใช่ OS ที่เขียนใหม่จากศูนย์

| ส่วน | สิ่งที่ได้ |
|------|-----------|
| ฐาน | Ubuntu 26.04 LTS + GNOME (มี GUI ใช้งานเหมือน desktop ปกติ) |
| ตัวตน | ชื่อ OS, boot splash, หน้า login, ธีม, ไอคอนสถานะรอสเต้บน top bar |
| รอสเต้ | ทุก worker เป็น systemd service — เปิดเครื่องแล้วรอสเต้ตื่นเอง |
| dev | VS Code + Claude Code (CLI + extension), toolchain STM32 ติดมาให้ |
| kernel | kernel ที่ build เอง + `roste_hw.ko` driver คุยกับ STM32 ผ่าน USB |
| ส่งมอบ | ISO เสียบ USB ลงเครื่องใหม่ได้ ได้สภาพเดิมทุกครั้ง |

---

## 1️⃣ เหตุผล — ทำไมต้องย้าย

### 1. การดูแล process บน Windows เป็นงานแก้ขัด ไม่ใช่ระบบ
- [`restart_bot.ps1`](../restart_bot.ps1) ต้อง kill process จาก **CommandLine** แทนชื่อ process เพราะ
  WindowsApps launcher re-exec `python.exe` เป็น `python3.13.exe` — เจอ orphan worker (RVC/F5)
  ค้างมาแล้ว**หลายรอบ**
- ROADMAP ข้อ "Auto-recovery ของ voice worker" ยังค้าง: worker ตายแล้ว TTS ปิดถาวรจนกว่าจะ restart เอง
- [`bot.py:187`](../bot.py#L187) ต้องระวังเรื่อง exit code เพราะ `start.bat` ตัดสินจาก exit code อย่างเดียว

บน Linux ทั้งหมดนี้คือ systemd ที่มีอยู่แล้ว: `Restart=on-failure` ให้ worker respawn เอง,
cgroup ของแต่ละ service ทำให้ kill แล้วลูกตายตามหมด (ไม่มี orphan), `journalctl` เก็บ log ทุก worker ที่เดียว

### 2. ทิศทางของโปรเจกต์คือ "สั่งงานโลกจริง" — Linux เป็นพื้นที่ของงาน hardware
วิสัยทัศน์ใน [ROADMAP](ROADMAP.md) คือ *ควบคุมอุปกรณ์ IoT ในบ้านได้ ทำงานในโลกจริงได้* และแผนถัดไปคือ
ต่อ STM32 เพื่อสั่งงานและรับ input แบบ real-time

| | Windows | Linux |
|---|---|---|
| เขียน driver เอง | KMDF/WDF + ต้อง sign driver (test-signing mode ถ้าไม่มี cert) | kernel module โหลดได้ทันที (`insmod`) |
| สิทธิ์เข้าถึง USB | ต้องลง WinUSB/Zadig ต่ออุปกรณ์ | udev rule บรรทัดเดียว ไม่ต้อง sudo |
| ลด latency | ทำได้จำกัด | PREEMPT_RT อยู่ใน mainline แล้ว (ตั้งแต่ 6.12) เปิดใน config ได้เลย |
| SocketCAN / spidev / IIO / input subsystem | ไม่มี | มีมาใน kernel |

การแบ่งงานที่ตั้งใจไว้: **hard real-time ทั้งหมดอยู่บน STM32** (sensor, มอเตอร์, timing ระดับ µs)
ส่วน Linux ทำ AI + ตัดสินใจ (ระดับ ms) — PC ตั้งโต๊ะไม่มี GPIO/SPI/I2C จึงคุยกันผ่าน **USB**

### 3. ติดตั้งซ้ำไม่ได้ = ย้ายเครื่องแต่ละครั้งเจ็บ
- ตอนนี้มี venv แยก **5 ตัว** (`venv`, `f5_venv`, `rvc_venv`, `typhoon_asr_venv`, `voxcpm_venv`)
  ตั้งด้วยมือผ่าน `setup.bat`
- โปรเจกต์ย้ายเครื่องมาแล้วหนึ่งครั้ง (โน้ตบุ๊ค 4GB → PC RTX 5060 Ti 16GB, ดู ROADMAP หัวข้อ "ย้ายเครื่อง")

Roste OS build จากสคริปต์ใน repo → ลงเครื่องใหม่ได้สภาพเดียวกันทุกครั้ง โมเดล AI ดาวน์โหลดตอน first-boot

### 4. ความปลอดภัยตอนเริ่มคุมอุปกรณ์จริง
ROADMAP บันทึกไว้แล้วว่า fact จาก "จำไว้ว่า..." จะกลายเป็น prompt injection ที่มีผลจริงทันทีที่มี tool
สั่งอุปกรณ์ — gate ต้องอยู่ในโค้ด ไม่ใช่ใน LLM บน Roste OS ทำเป็นชั้นของ OS ได้อีกชั้น:
- `hw_bridge` เป็น service แยก รันด้วย user ของตัวเอง เป็นตัวเดียวที่มีสิทธิ์เปิด `/dev/roste_hw`
- บอทสั่งอุปกรณ์ได้ผ่าน `hw_bridge` เท่านั้น ซึ่งตรวจ `user_id` + ช่วงค่าที่อนุญาตก่อนส่งถึง STM32
- STM32 มี watchdog ของตัวเอง: ถ้าฝั่ง Linux เงียบเกินกำหนด → กลับสถานะปลอดภัยเอง

### 5. เครื่องพัฒนาพร้อมใช้ตั้งแต่ลงเสร็จ
VS Code + Claude Code + `arm-none-eabi-gcc` / OpenOCD / STM32CubeProgrammer + udev rule ของ ST-Link
ติดมาใน image — เปิดเครื่องแล้วแก้โค้ดบอทและ flash STM32 ได้จากเครื่องเดียว
(Claude Code ต้อง login เองหลังลงเครื่อง — **ห้ามฝัง token ไว้ใน ISO**)

### 6. VRAM ที่ desktop ไม่ต้องแบ่ง — *ยังไม่ได้วัด*
คาดว่า Linux ที่ไม่มีงานอื่นแย่ง GPU จะเหลือ VRAM ให้รอสเต้มากกว่า Windows ที่เปิดใช้งานทั่วไป
แต่**ยังไม่มีตัวเลข** — ต้องวัดด้วย `nvidia-smi` ตอนว่างบนทั้งสอง OS ก่อนนับเป็นเหตุผล
(อ้างอิงที่วัดแล้วบน Windows: qwen3-vl 5.79 + qwen3:8b 5.58 + bge-m3 0.66 = 12.04GB / 16.31GB)

---

## 2️⃣ สิ่งที่ต้องแลก — ย้ายแล้วอะไรพัง

| เรื่อง | ผลกระทบ | ทางแก้ |
|------|---------|--------|
| [`printing.py`](../printing.py) | ใช้ `win32print` + SumatraPDF ทั้งไฟล์ — **ใช้บน Linux ไม่ได้เลย** | เขียนใหม่เป็น CUPS (`lp` / `pycups`) |
| Canon E3300 | ไม่ต้องพึ่ง driver ของรุ่นนี้ | เปลี่ยนเป็นเครื่องพิมพ์ไร้สายที่รองรับ **IPP Everywhere / AirPrint** — CUPS พิมพ์ได้แบบ driverless และ IPP รายงานระดับหมึก/สถานะกระดาษได้ (แก้ข้อจำกัด "Canon USB ไม่รายงานสถานะหมึก" ใน ROADMAP ไปด้วย — *ยังไม่ได้ลองกับเครื่องจริง*) |
| `start.bat`, `setup.bat`, `restart_bot.ps1` | ใช้ไม่ได้ | แทนด้วย systemd units + สคริปต์ติดตั้ง |
| RTX 5060 Ti (Blackwell) | ต้องใช้ driver ใหม่ + CUDA 12.8 ขึ้นไป + PyTorch build cu128 | เช็คทุก venv (F5/RVC/VoxCPM/Typhoon) ว่า build กับ CUDA ใหม่ได้ |
| worker ทั้ง 5 venv | ยังไม่เคยรันบน Linux | ต้องเทสทีละตัว ไม่ถือว่าผ่านจนกว่าจะรันจริง |
| เวลา | แย่งเวลากับงานที่ค้าง (wake word ใน roste-plan.md รอบ 4, task state machine) | ทำเป็นเฟส ไม่หยุดงานบอท |

[`stt_client.py:38`](../stt_client.py#L38) เช็ค `sys.platform` ไว้แล้ว ไม่ต้องแก้

---

## 3️⃣ ทางเลือกที่พิจารณาแล้ว

| ทางเลือก | ผล | เหตุผล |
|---------|----|--------|
| อยู่ Windows ต่อ + Docker/WSL2 | ❌ ไม่พอ | แก้ข้อ 1 กับ 3 ได้ แต่งาน driver/USB/real-time (ข้อ 2) ยังติดอยู่บน Windows |
| Ubuntu ธรรมดา ไม่ปรับอะไร | 🟡 จุดเริ่มต้น | ได้ข้อ 1, 2, 4 แต่ลงซ้ำไม่ได้ (ข้อ 3) — เป็นเฟส 1 ของแผนนี้ |
| **Ubuntu ที่ปรับเป็น Roste OS** | ✅ **เลือก** | ได้ครบทุกข้อ CUDA/ไดรเวอร์ NVIDIA ยังใช้ของสำเร็จรูปได้ |
| Buildroot / Yocto | ❌ | ได้ image เล็กแต่ต้องประกอบ NVIDIA driver + CUDA เอง — งานหนักสุดไปตกที่ส่วนที่ไม่ได้อยากทำ |
| เขียน OS / kernel ใหม่ทั้งหมด | ❌ | ไม่มี CUDA, PyTorch, ไดรเวอร์ — ต้อง port ทุกอย่างเอง และคอขวดของรอสเต้อยู่ที่ GPU ไม่ใช่ OS |

**เขียน kernel เองเฉพาะส่วนที่ได้ประโยชน์จริง** — คือ driver ของ STM32 ส่วนอื่นใช้ของ mainline

---

## 4️⃣ ลำดับงาน

1. **ลง Ubuntu ธรรมดา** แล้วย้ายรอสเต้มารันผ่าน systemd ให้ครบทุก worker + แก้ `printing.py` เป็น CUPS
   — *ผ่านเฟสนี้เมื่อ:* เทสทั้งหมดผ่านบน Linux และใช้งานจริงได้เท่า Windows
2. **STM32 แบบ USB CDC** (`/dev/ttyACM*`) + protocol (COBS + CRC + seq/ACK + watchdog) + `hw_bridge`
   ฝั่ง userspace ต่อเข้า `llm_tools.py` — *วัด latency จริงเก็บไว้*
3. **`roste_hw.ko`** — USB vendor-class driver แทน CDC (ทำเมื่อเฟส 2 ใช้งานได้แล้วเท่านั้น)
   ให้ input จาก STM32 ขึ้นเป็น `/dev/input/eventX` หรือ `/dev/roste_hw` — build ผ่าน DKMS
4. **Roste OS image** — branding + VS Code + Claude Code + toolchain STM32 + kernel ของเรา
   เวอร์ชันแรกทำด้วย Cubic (แก้ ISO ของ Ubuntu) แล้วย้ายเป็นสคริปต์ build ใน `roste-os/`

---

## ❓ คำถามที่ยังเปิด

- [x] ~~Canon E3300 มี driver Linux ไหม~~ → ไม่ต้องสน: เปลี่ยนเป็นเครื่องพิมพ์ไร้สายที่รองรับ IPP Everywhere
- [ ] เลือกรุ่นเครื่องพิมพ์ — เช็คว่ารองรับ IPP Everywhere ก่อนซื้อ (ดูรายชื่อที่ OpenPrinting)
- [ ] STM32 จะต่ออะไรบ้าง (ปุ่ม / sensor / มอเตอร์ / ไฟ) และต้องการ latency เท่าไหร่ — กำหนดว่าเฟส 3 จำเป็นไหม
- [ ] ลงบนเครื่อง RTX 5060 Ti ตัวปัจจุบัน หรือเครื่องที่จะประกอบใหม่ — ถ้าเครื่องเดิม ต้องทำ dual-boot ระหว่างย้าย
- [ ] ข้อ 6 (VRAM) — วัด `nvidia-smi` ตอนว่างบนทั้งสอง OS
