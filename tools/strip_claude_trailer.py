"""ลบบรรทัด Co-Authored-By: Claude ออกจากทุกคอมมิต

รัน:
    python tools/strip_claude_trailer.py          # เช็ค logic อย่างเดียว ไม่แตะ repo
    python tools/strip_claude_trailer.py --run    # แก้จริง

⚠️ เขียนประวัติใหม่ — SHA เปลี่ยนทุกคอมมิต ต้อง push --force ทับ remote
   กู้คืนด้วย: git reset --hard <backup-branch>

หมายเหตุ: เรียก git_filter_repo เป็น library ไม่ส่ง --message-callback ผ่าน
command line เพราะ escape sequence (\t \n) โดนแปลงเป็นตัวอักษรจริงระหว่างทาง
ทำให้ regex ขาดกลางแล้ว SyntaxError (เจอจริงตอนรันครั้งแรก)
"""
import re, subprocess, sys

PAT = re.compile(rb"(?im)^Co-Authored-By:[ \t]*Claude[^\n]*\r?\n?")


def strip(msg: bytes) -> bytes:
    return PAT.sub(b"", msg).rstrip() + b"\n"


def selftest() -> bool:
    cases = [
        (b"fix: aaa\n\nrationale\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n",
         b"fix: aaa\n\nrationale\n"),
        (b"feat: bbb\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n",
         b"feat: bbb\n"),
        (b"fix: ccc\n\nCo-Authored-By: Somchai <s@example.com>\n",
         b"fix: ccc\n\nCo-Authored-By: Somchai <s@example.com>\n"),   # คนอื่นต้องไม่โดนลบ
        (b"docs: ddd\n", b"docs: ddd\n"),
    ]
    ok = True
    for i, (src, want) in enumerate(cases, 1):
        got = strip(src)
        print(f"  selftest {i} {'ok' if got == want else 'FAIL'}")
        if got != want:
            print(f"    got : {got!r}\n    want: {want!r}")
            ok = False
    return ok


def count_trailers() -> int:
    out = subprocess.run(["git", "log", "--format=%b"], capture_output=True).stdout
    return out.count(b"Co-Authored-By: Claude")


if __name__ == "__main__":
    print("ตรวจ logic ก่อน:")
    if not selftest():
        sys.exit("selftest ไม่ผ่าน — ไม่แตะ repo")

    if "--run" not in sys.argv:
        print(f"\nselftest ผ่าน | ตอนนี้มี trailer {count_trailers()} จุด")
        print("รันจริง: python tools/strip_claude_trailer.py --run")
        sys.exit(0)

    print(f"\nก่อนแก้: trailer {count_trailers()} จุด")

    import git_filter_repo as fr

    def msg_cb(message, _md=None):
        return strip(message)

    args = fr.FilteringOptions.parse_args(["--force", "--quiet"], error_on_empty=False)
    fr.RepoFilter(args, message_callback=msg_cb).run()

    print(f"หลังแก้ : trailer {count_trailers()} จุด")
    print(f"คอมมิต  : {subprocess.run(['git','rev-list','--count','HEAD'],capture_output=True,text=True).stdout.strip()}")
    print("\n⚠️ git-filter-repo ลบ remote ทิ้งกันเผลอ push — เช็คด้วย git remote -v")
