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

**เปิดจากมือถือในวงแลนบ้าน:** service ที่ติดตั้งไว้รันด้วย `--host 0.0.0.0` อยู่แล้ว กดปุ่ม **มือถือ** ในหน้าเว็บจะมี QR code ให้สแกน ลิงก์มีรหัส `?token=...` อยู่ในตัว (เก็บไว้ที่ `.web_token` ลิงก์เดิมใช้ได้ตลอดแม้รีสตาร์ท ลบไฟล์นี้ทิ้งเพื่อเปลี่ยนรหัส) เปิดจากคอมเครื่องนี้เองไม่ต้องใช้รหัส อย่าแชร์ลิงก์ให้คนที่ไม่ไว้ใจ และอย่าเปิดพอร์ตนี้ออกอินเทอร์เน็ต ถ้า firewall บล็อกพอร์ต ให้เปิดด้วย `sudo firewall-cmd --add-port=8080/tcp`

**ลบคลิป:** ปุ่มถังขยะบนคลิปแต่ละอัน ส่วน **ลบคลิปเก่าอัตโนมัติ** ตั้งได้ที่ใต้แถบพื้นที่ดิสก์ (ปิดไว้เป็นค่าเริ่มต้น) เมื่อพื้นที่ว่างต่ำกว่าค่าที่ตั้ง จะลบ MP4 ที่เก่าที่สุดก่อน ไม่แตะคลิปที่กำลังอัด ไฟล์ย่อยที่ยังไม่รวม หรือคลิปที่กำลังอัปโหลด

**สถิติบนการ์ดไลฟ์:** TikTok ส่งยอดกดใจ ของขวัญ และเพชรมาเป็น 0 ในข้อมูลห้องไลฟ์แบบปกติ ยอดคนส่งของขวัญและเพชรจึงนับจากรายชื่อ "ผู้ชมอันดับต้นของไลฟ์" ทุก 1 นาที (คนที่ส่งแล้วออกไปก่อนโปรแกรมเห็นจะไม่ถูกนับ ตัวเลขจึงต่ำกว่าจริงได้) ยอดกดใจมีแค่ทางช่องแชตแบบเข้ารหัสลายเซ็นที่โปรแกรมไม่ใช้ จึงแสดง "ติดตามใหม่" แทน

## อัปโหลดขึ้น YouTube (ส่วนตัว)

ใช้ YouTube Data API ด้วยบัญชี Google ของคุณเอง ตั้งค่าครั้งเดียว:

1. เปิด https://console.cloud.google.com/projectcreate สร้างโปรเจกต์ใหม่ (ฟรี)
2. เปิดใช้ **YouTube Data API v3** ที่ https://console.cloud.google.com/apis/library/youtube.googleapis.com
3. ตั้ง **OAuth consent screen** (https://console.cloud.google.com/auth/overview) แบบ **External** แล้วไปที่ **Audience** กด **Publish app** (ไม่ต้องส่งให้ Google ตรวจ ถ้าค้างเป็น Testing สิทธิ์จะหมดทุก 7 วันและอัปโหลดอัตโนมัติจะหยุด)
4. ที่ https://console.cloud.google.com/auth/clients กด Create client เลือกชนิด **Desktop app** แล้วดาวน์โหลดไฟล์ JSON
5. ย้ายไฟล์นั้นมาไว้ในโฟลเดอร์โปรแกรม ตั้งชื่อ `client_secret.json`
6. ในหน้าเว็บกดปุ่ม **YouTube** → **เชื่อมบัญชี Google** แล้วอนุญาต (Google จะเตือนว่าแอปยังไม่ผ่านการตรวจ ให้กด Advanced → Continue เพราะเป็นแอปของคุณเอง)
   - เปิดหน้าเว็บจากเครื่องที่รันโปรแกรม: กลับมาหน้าเว็บเอง
   - เปิดจากที่อื่น (มือถือ, ผ่าน Cloudflare Tunnel): หลังอนุญาต เบราว์เซอร์จะไปหน้า `http://127.0.0.1:8080/oauth/youtube?...` ที่เปิดไม่ขึ้น เป็นเรื่องปกติ ให้คัดลอกที่อยู่ทั้งบรรทัดมาวางในช่องที่หน้าเว็บแสดง
   - หรือใช้คำสั่งในเทอร์มินัล: `python3 -m ttlive youtube-login` (ทำแบบเดียวกัน วางที่อยู่ในเทอร์มินัล)

จากนั้นกดไอคอน YouTube บนคลิปเพื่ออัปโหลด หรือเปิดสวิตช์ **อัปโหลดอัตโนมัติทุกคลิปที่อัดเสร็จ** ในหน้าต่าง YouTube (`youtube_auto_upload` ใน config) คลิปจะเป็น **Private** เสมอ อัปทีละคลิปตามลำดับ ขอสิทธิ์แค่ `youtube.upload` โควตาฟรีอัปได้ราว 6 คลิปต่อวัน ถ้าอัปไม่สำเร็จจะแจ้งเตือนและกดอัปใหม่ได้จากคลิปนั้น

## รันบน VPS (Ubuntu Server) + Cloudflare Tunnel

บน VPS ไม่มี Chrome จึงใช้ `cookies.txt` ที่อัปโหลดผ่านหน้าเว็บ (ล็อกอิน TikTok ใน Chrome บนคอม แล้ว export ด้วยส่วนขยาย "Get cookies.txt LOCALLY") หน้าเว็บฟังแค่ `127.0.0.1:8080` ไม่เปิดพอร์ตออกเน็ต เข้าจากข้างนอกผ่าน Cloudflare Tunnel และต้องมี token เสมอ (คำขอที่มาทาง tunnel/proxy จะไม่ถูกนับว่าเป็น "เครื่องตัวเอง")

**1. สร้าง tunnel ใน Cloudflare (ต้องมีโดเมนที่อยู่ใน Cloudflare)**
<https://one.dash.cloudflare.com> → Networks → Tunnels → Create a tunnel → Cloudflared → ตั้งชื่อ → คัดลอก token (ตัวยาวที่ขึ้นต้นด้วย `eyJ`) → แท็บ Public Hostname: เช่น `rec.example.com` → Service `HTTP` `localhost:8080`

**2. เอาโค้ดขึ้น VPS แล้วติดตั้ง**

```bash
ssh ubuntu@<ที่อยู่ VPS>
sudo apt update && sudo apt install -y git
git clone https://github.com/Sitthidet-SR/Tiktok-Download-Live.git TikTok-Download-Live
cd TikTok-Download-Live
bash deploy/install-ubuntu.sh --cloudflare https://rec.example.com
```

สคริปต์จะติดตั้ง python3, ffmpeg, cloudflared สร้าง service `ttlive` (เริ่มเองตอนบูต, ใช้เวลาไทย) แล้วถาม tunnel token (พิมพ์แล้วไม่แสดงบนจอ) ตอนจบจะพิมพ์ลิงก์ `https://rec.example.com/?token=...` ให้ เปิดครั้งเดียวแล้วเบราว์เซอร์จำไว้ 1 ปี

ถ้าไม่ใช้ Cloudflare รันแค่ `bash deploy/install-ubuntu.sh` แล้วเข้าหน้าเว็บผ่าน SSH tunnel: `ssh -L 8080:127.0.0.1:8080 ubuntu@<ที่อยู่ VPS>` แล้วเปิด <http://localhost:8080>

**3. ย้ายไฟล์ลับจากคอม (ถ้ามี)** ไฟล์เหล่านี้ไม่อยู่ใน git: `cookies.txt`, `client_secret.json`, `youtube_token.json`, `config.json`

```bash
scp cookies.txt client_secret.json youtube_token.json ubuntu@<ที่อยู่ VPS>:TikTok-Download-Live/
```

หรือ `bash deploy/push-to-vps.sh ubuntu@<ที่อยู่ VPS>` เพื่อคัดลอกทั้งโฟลเดอร์ (ยกเว้นคลิปและ log) แล้วรัน install ซ้ำ ไม่มีก็ได้: อัปโหลด cookie และเชื่อม YouTube จากหน้าเว็บ

**4. ในหน้าเว็บ** อัปโหลด cookies.txt → เพิ่มช่อง → ปุ่ม YouTube → เชื่อมบัญชี (แบบวางที่อยู่) → เปิด **อัปโหลดอัตโนมัติ** แนะนำเปิด **ลบคลิปเก่าอัตโนมัติ** ด้วยเพราะดิสก์ VPS มักเล็ก

คำสั่งบน VPS: `sudo systemctl status ttlive`, `sudo systemctl restart ttlive`, `journalctl -u ttlive -f` (ดู log) อัปเดตโค้ด: `git pull && sudo systemctl restart ttlive` (รอให้ไม่มีไลฟ์ที่กำลังอัดก่อน)

ข้อควรรู้: IP ของ VPS เป็น IP ดาต้าเซ็นเตอร์ TikTok อาจขึ้น CAPTCHA บ่อยกว่าที่บ้าน ถ้าเจอโปรแกรมจะหยุดเช็กชั่วคราวและแจ้งเตือน ให้เปิด tiktok.com ใน Chrome บนคอม ยืนยันตัวตน แล้ว export cookies.txt ใหม่มาอัปโหลด

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

## อ่าน cookie จาก Chrome อัตโนมัติ (แนะนำ)

ใส่ `"cookies_from_browser": "chrome"` ใน `config.json` (และ `"browser_profile"` ถ้าไม่ได้ใช้โปรไฟล์ `Default`) โปรแกรมจะอ่าน cookie ของ tiktok.com จาก Chrome ในเครื่องเองทุก 1 นาที แล้วเขียนลง `cookies.txt` ให้ ไม่ต้อง export เอง อ่านเฉพาะ cookie ของ tiktok.com เท่านั้น ใช้กุญแจ "Chrome Safe Storage" จาก KWallet หรือ keyring ของเครื่อง และถอดรหัสด้วยคำสั่ง `openssl`

## เมื่อเจอ CAPTCHA หรือ cookie หมดอายุ

โปรแกรมจะ **ไม่** พยายามแก้หรือหลบ CAPTCHA แต่จะหยุดส่งคำขอทั้งหมดตาม `captcha_pause_minutes` และแจ้งเตือน (ไลฟ์ที่กำลังอัดอยู่ยังอัดต่อ)

**ถ้าตั้งให้อ่าน cookie จาก Chrome:** กดปุ่ม "เปิด TikTok" ในแถบเตือน ยืนยันตัวตนใน Chrome แล้วกด "ยืนยันแล้ว ทำงานต่อ" โปรแกรมจะดึง cookie ใหม่และลองเช็ก 1 ครั้ง ถ้าผ่านก็ทำงานต่อทันที ถ้าไม่กดปุ่ม โปรแกรมจะลองเองไม่เกิน 1 ครั้งทุก 2 นาทีเมื่อเห็น cookie ใน Chrome เปลี่ยน

**ถ้าใช้ไฟล์ cookies.txt:**

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
