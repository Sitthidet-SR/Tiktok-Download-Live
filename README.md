# TikTok Download Live

โปรแกรม command line (Python) สำหรับเฝ้าดูช่อง TikTok ที่เลือกไว้ พอช่องเริ่มไลฟ์ก็บันทึกด้วย ffmpeg ทันที ถ้าสตรีมหลุดจะเชื่อมต่อใหม่เอง และรวมไฟล์เป็น .mp4 เมื่อไลฟ์จบ

ใช้แค่ไลบรารีมาตรฐานของ Python 3.9+ กับ ffmpeg ไม่ต้อง `pip install` อะไรเพิ่ม

> ใช้กับไลฟ์ของตัวเองหรือช่องที่ได้รับอนุญาตเท่านั้น ข้อตกลงของ TikTok ห้ามดาวน์โหลดด้วยเครื่องมืออัตโนมัติ บัญชีที่ใช้จึงมีความเสี่ยงถูกจำกัดหรือแบน

## เริ่มเร็วที่สุด: หน้าเว็บ

```bash
cd ~/TikTok-Download-Live
python3 -m ttlive web --open
```

แล้วเปิด <http://localhost:8080> (ใส่ `--open` จะเปิดเบราว์เซอร์ให้เอง) ในหน้าเว็บทำได้ทุกอย่าง:

- อัปโหลด `cookies.txt` (ลากไฟล์มาวาง)
- เพิ่มหรือลบช่อง, กด "เช็กตอนนี้", หยุดเฝ้าหรือหยุดบันทึกทีละช่อง (รายชื่อช่องถูกบันทึกลง `config.json` ให้อัตโนมัติ)
- เห็นรูปโปรไฟล์และชื่อของแต่ละช่อง
- ดูช่องที่กำลังบันทึกพร้อมยอดคนดูตอนนี้ ยอดกดใจ คนเข้าดูทั้งหมด เวลา ขนาดไฟล์ และคุณภาพ
- เปิดดูวิดีโอที่บันทึกแล้วในเบราว์เซอร์ หรือดาวน์โหลด, รวมไฟล์ .ts ที่ค้างเป็น .mp4
- แถบเตือนเมื่อเจอ CAPTCHA, HTTP 429 หรือ cookie หมดอายุ และรายการกิจกรรมล่าสุด

ถ้ายังไม่มี `config.json` โปรแกรมจะสร้างให้เอง ปิดหน้าเว็บได้โดยการบันทึกยังทำงานต่อ กด Ctrl+C ในเทอร์มินัลเพื่อหยุดโปรแกรม

**เปิดจากมือถือในวงแลนบ้าน:** `python3 -m ttlive web --host 0.0.0.0` โปรแกรมจะพิมพ์ลิงก์ที่มี `?token=...` ให้ ต้องเปิดด้วยลิงก์นั้นเท่านั้น (กันคนอื่นในเครือข่ายเข้ามาใช้) อย่าแชร์ลิงก์นี้ให้คนที่ไม่ไว้ใจ และอย่าเปิดพอร์ตนี้ออกอินเทอร์เน็ต ถ้า Fedora บล็อกพอร์ต ให้เปิดด้วย `sudo firewall-cmd --add-port=8080/tcp`

## เปิดเองหลังรีสตาร์ทเครื่อง

ใช้ systemd user service (ไฟล์อยู่ที่ `contrib/ttlive.service`) กินแรมราว 30 MB และ CPU แทบเป็นศูนย์ตอนรอ ระหว่างบันทึก ffmpeg ใช้ราว 90 MB และ CPU ไม่ถึง 1% ต่อไลฟ์ เพราะไม่ได้เข้ารหัสใหม่

```bash
mkdir -p ~/.config/systemd/user
cp contrib/ttlive.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ttlive.service
loginctl enable-linger "$USER"    # ให้เริ่มตอนบูตแม้ยังไม่ได้ล็อกอิน
```

คำสั่งที่ใช้บ่อย: `systemctl --user status ttlive` (ดูสถานะ), `systemctl --user restart ttlive` (รีสตาร์ท), `systemctl --user stop ttlive` (หยุด) ตอนหยุดหรือปิดเครื่อง โปรแกรมจะปิดไฟล์ที่กำลังบันทึกและรวมคลิปให้ก่อน (รอได้สูงสุด 5 นาที) log อยู่ใน `ttlive.log`

## ติดตั้ง

```bash
sudo dnf install ffmpeg        # Fedora (Ubuntu: sudo apt install ffmpeg)
cd ~/TikTok-Download-Live
cp config.example.json config.json
```

## เตรียม cookie (บัญชีของเราเอง)

1. ล็อกอิน tiktok.com ในเบราว์เซอร์
2. Export cookie เป็นไฟล์ `cookies.txt` รูปแบบ Netscape ด้วยส่วนขยายที่เชื่อถือได้ (เช่น "Get cookies.txt LOCALLY")
3. วางไฟล์ไว้ในโฟลเดอร์นี้ แล้วตั้งสิทธิ์ให้อ่านได้เฉพาะเรา: `chmod 600 cookies.txt`

cookie มีค่าเท่ากับรหัสผ่านบัญชี ห้ามส่งให้ใคร ไฟล์ `cookies.txt` และ `config.json` อยู่ใน `.gitignore` แล้ว

## ตั้งค่า `config.json`

| ค่า | ค่าเริ่มต้น | ความหมาย |
| --- | --- | --- |
| `channels` | – | ชื่อผู้ใช้ที่จะเฝ้า (มีหรือไม่มี @ ก็ได้) แนะนำเริ่มที่ 5–10 ช่อง |
| `cookies_file` | `cookies.txt` | ที่อยู่ไฟล์ cookie |
| `output_dir` | `recordings` | โฟลเดอร์เก็บไฟล์ |
| `check_interval_min` / `max` | 60 / 180 | เช็กสถานะแต่ละช่องทุกกี่วินาที (สุ่มในช่วงนี้ ต่ำสุดที่ยอมคือ 30) |
| `jitter` | 0.2 | สุ่มเวลาเพิ่ม/ลด ±20% |
| `min_request_gap` | 3 | เว้นระยะขั้นต่ำระหว่างคำขอใด ๆ ไป TikTok (วินาที) |
| `segment_seconds` | 1800 | แบ่งไฟล์ .ts ทุก 30 นาที |
| `stats_interval` | 60 | ระหว่างบันทึก อัปเดตยอดคนดูและยอดกดใจทุกกี่วินาที (ต่ำสุด 30) |
| `stream_preference` | origin, uhd, FULL_HD1, … | ลำดับคุณภาพที่ต้องการ (สูงสุดก่อน) ไฟล์ log จะบอกว่าแต่ละไลฟ์มีคุณภาพไหนให้เลือก |
| `rejoin_minutes` | 8 | ถ้าไลฟ์หลุดหรือคนไลฟ์ปิดแล้วเปิดใหม่ภายในเวลานี้ (นาที) จะต่อเป็นคลิปเดียวกัน ถ้านานกว่านี้จะขึ้นคลิปใหม่ |
| `reconnect_delays` | 5, 10, 20, 30 | ระหว่างรอไลฟ์กลับมา เช็กซ้ำห่างกันกี่วินาที (สูงสุด 30) |
| `merge_on_end` | true | รวม .ts เป็น .mp4 เมื่อไลฟ์จบ |
| `delete_segments_after_merge` | true | ลบ .ts หลังรวมสำเร็จ (ลบเฉพาะเมื่อตรวจแล้วว่าไฟล์ MP4 ยาวครบ) |
| `captcha_pause_minutes` | 30 | หยุดนานเท่าไรเมื่อเจอ CAPTCHA |
| `discord_webhook_url` | ว่าง | ใส่ถ้าอยากได้แจ้งเตือนทาง Discord |
| `line_channel_token` / `line_to` | ว่าง | ใส่ถ้าอยากได้แจ้งเตือนทาง LINE Messaging API (token ของ channel + user ID ผู้รับ) |

## วิธีใช้

```bash
# เช็กว่า cookie ล็อกอินอยู่ และดูสถานะช่องครั้งเดียว
python3 -m ttlive check
python3 -m ttlive check someuser --stream    # ดึง URL สตรีมด้วยถ้ากำลังไลฟ์

# เริ่มเฝ้าดูและบันทึกแบบไม่มีหน้าเว็บ (กด Ctrl+C เพื่อหยุด ไฟล์ที่บันทึกอยู่จะถูกปิดและรวมให้)
python3 -m ttlive run

# รวมไฟล์เองภายหลัง
python3 -m ttlive merge recordings/someuser/someuser_20261027_200000 --delete
```

ใส่ `-v` เพื่อดู log ละเอียด (รวม output ของ ffmpeg) และ `-c path/config.json` ถ้า config อยู่ที่อื่น

ถ้าอยากให้รันค้างไว้หลังปิดเทอร์มินัล ใช้ `tmux` หรือ `nohup python3 -m ttlive run > ttlive.log 2>&1 &`

ไฟล์จะอยู่ที่ `recordings/<user>/<user>_<วันเวลา>/*.ts` ระหว่างบันทึก และ `recordings/<user>/<user>_<วันเวลา>.mp4` หลังไลฟ์จบ

## เมื่อเจอ CAPTCHA หรือ cookie หมดอายุ

โปรแกรมจะ **ไม่** พยายามแก้หรือหลบ CAPTCHA แต่จะหยุดส่งคำขอทั้งหมดตาม `captcha_pause_minutes` และแจ้งเตือน

1. เปิด tiktok.com ในเบราว์เซอร์แล้วยืนยันตัวตนเอง
2. Export `cookies.txt` ใหม่ทับไฟล์เดิม

โปรแกรมเห็นว่าไฟล์ cookie เปลี่ยนแล้วจะโหลดใหม่และทำงานต่อเองโดยไม่ต้องรีสตาร์ท

ถ้าเจอ HTTP 429 จะรอตาม `Retry-After` หรือถ้าไม่มีก็รอ 2, 4, 8 … นาที สูงสุด 30 นาที

## โครงสร้างโค้ด

| ไฟล์ | หน้าที่ |
| --- | --- |
| `ttlive/http_client.py` | HTTP client ตัวเดียวของทั้งโปรแกรม: cookie, เว้นระยะคำขอ, backoff 429, ตรวจ CAPTCHA |
| `ttlive/tiktok_api.py` | หา room ID, เช็กสถานะไลฟ์, ดึง URL สตรีม |
| `ttlive/monitor.py` | ลูปเฝ้าดูทุกช่อง |
| `ttlive/recorder.py` | บันทึกด้วย ffmpeg หนึ่ง process ต่อไลฟ์ พร้อม reconnect |
| `ttlive/merge.py` | รวม .ts เป็น .mp4 |
| `ttlive/notifier.py` | แจ้งเตือนใน log, Discord, LINE |
| `ttlive/web.py` | เว็บเซิร์ฟเวอร์และ API ของหน้าเว็บ |
| `ttlive/static/` | หน้าเว็บ (HTML, CSS, JavaScript) |

endpoint ที่ใช้เป็น API ที่ไม่เปิดเผยของเว็บ TikTok เปลี่ยนได้ตลอด ถ้าวันหนึ่งใช้ไม่ได้ ให้เทียบกับ extractor `tiktok:live` ของ yt-dlp

## ทดสอบ

```bash
python3 -m unittest -v tests/test_ttlive.py
```
