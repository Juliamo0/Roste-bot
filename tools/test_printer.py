# อ่านสถานะเครื่องพิมพ์ผ่าน win32print เพื่อดูว่าระบบอ่านอะไรได้บ้าง
# วิธีใช้: python test_printer.py
import win32print

PRINTER = "Canon E3300 series"   # แก้ให้ตรงชื่อเครื่องถ้าต่าง

# ค่าคงที่สถานะทั้งหมดที่ Windows รู้จัก
STATUS_FLAGS = [
    "PRINTER_STATUS_PAUSED", "PRINTER_STATUS_ERROR", "PRINTER_STATUS_PENDING_DELETION",
    "PRINTER_STATUS_PAPER_JAM", "PRINTER_STATUS_PAPER_OUT", "PRINTER_STATUS_MANUAL_FEED",
    "PRINTER_STATUS_PAPER_PROBLEM", "PRINTER_STATUS_OFFLINE", "PRINTER_STATUS_IO_ACTIVE",
    "PRINTER_STATUS_BUSY", "PRINTER_STATUS_PRINTING", "PRINTER_STATUS_OUTPUT_BIN_FULL",
    "PRINTER_STATUS_NOT_AVAILABLE", "PRINTER_STATUS_WAITING", "PRINTER_STATUS_PROCESSING",
    "PRINTER_STATUS_INITIALIZING", "PRINTER_STATUS_WARMING_UP", "PRINTER_STATUS_TONER_LOW",
    "PRINTER_STATUS_NO_TONER", "PRINTER_STATUS_PAGE_PUNT", "PRINTER_STATUS_USER_INTERVENTION",
    "PRINTER_STATUS_OUT_OF_MEMORY", "PRINTER_STATUS_DOOR_OPEN", "PRINTER_STATUS_SERVER_UNKNOWN",
    "PRINTER_STATUS_POWER_SAVE",
]

print(f"=== อ่านสถานะเครื่องพิมพ์: {PRINTER!r} ===\n")
try:
    h = win32print.OpenPrinter(PRINTER)
except Exception as e:
    print("❌ เปิดเครื่องพิมพ์ไม่ได้:", e)
    print("   ลองเช็กชื่อเครื่องพิมพ์ใน Settings > Printers & scanners ให้ตรง")
    raise SystemExit

info = win32print.GetPrinter(h, 2)
win32print.ClosePrinter(h)

status = info.get("Status", 0)
print(f"ค่า Status ดิบ = {status}")
print(f"จำนวนงานในคิว (cJobs) = {info.get('cJobs', 0)}\n")

print("สถานะที่ตรวจพบ (ติ๊กถูก = เป็นอยู่ตอนนี้):")
found = False
for name in STATUS_FLAGS:
    flag = getattr(win32print, name, 0)
    if flag and (status & flag):
        print(f"   ✅ {name}")
        found = True
if not found:
    print("   (ไม่พบสถานะพิเศษใดๆ — เครื่องปกติ/พร้อมพิมพ์ หรือเครื่องไม่ได้รายงานสถานะ)")

print("\n--- เอาผลทั้งหมดนี้ไปให้ผู้ช่วยดูได้เลย ---")
