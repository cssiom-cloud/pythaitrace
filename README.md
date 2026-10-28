# PyThaiTrace 🇹🇭⚡
> **Bilingual Developer Diagnostic CLI Tool for Python**  
> คง Original English Traceback ไว้ 100% พร้อมแสดงการ์ดโมเดลความคิดภาษาไทย (Thai Mental Model) เพื่อการเรียนรู้และการดีบั๊กที่รวดเร็ว

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-457%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🌟 จุดเด่น (Key Features)

1. **Searchability First**: คงข้อความ Original English Traceback ดั้งเดิมของ Python ไว้ 100% บน `stderr` เพื่อให้สามารถนำข้อความไปค้นหาใน Google / StackOverflow ได้ตามปกติ
2. **Thai Mental Model Card**: อธิบายข้อผิดพลาดด้วยภาษาไทยที่เป็นธรรมชาติ เข้าใจกรอบความคิด (Mental Model) ว่าทำไม Python ถึงแจ้งเตือนแบบนี้ พร้อมวิธีแก้ไขและตัวอย่างโค้ด
3. **Adaptive Responsive UI (Termux & VSCode)**:
   - **Wide Mode ($\ge 80$ cols)**: แสดงผลกล่องพาเนล Rich สองชั้นสวยงามสำหรับ VSCode / Terminal ทั่วไป
   - **Narrow Mode ($< 80$ cols)**: แสดงผลแบบ Flat Layout พร้อมแถบสีขอบซ้าย `▌` และตัดคำภาษาไทยแบบพับบรรทัด (`overflow="fold"`) ออกแบบมาเพื่อหน้าจอมือถือใน **Termux** โดยเฉพาะ
4. **Pre-Execution Compilation Check**: ดักจับ `SyntaxError` และ `IndentationError` ได้ทันทีตั้งแต่ก่อนเริ่มรันสคริปต์
5. **Universal Thread & Async Context**: ดักจับได้ทั้ง Main thread, Worker thread (`threading.excepthook`) และ Async tasks
6. **Universal Fallback Engine**: รองรับ Exception ทุกชนิดจาก Third-party library หรือ Custom Exception พร้อมสกัด Docstring และสร้างคีย์เวิร์ดค้นหาให้อัตโนมัติ
7. **Zero-Crash Guarantee**: มีระบบ Fail-safe ป้องกันไม่ให้ตัวเครื่องมือแครชเองในทุกกรณี

---

## 📦 วิธีติดตั้ง (Installation)

### ติดตั้งบน Termux (Android) หรือเครื่องทั่วไปผ่าน GitHub
```bash
pip install git+https://github.com/cssiom-cloud/pythaitrace.git
```

> **กรณีขึ้นว่า `command not found: thpy` ใน Termux**:
> ```bash
> echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
> source ~/.bashrc
> ```

### ติดตั้งแบบ Clone โค้ดลงเครื่อง
```bash
git clone https://github.com/cssiom-cloud/pythaitrace.git
cd pythaitrace
pip install -e .
```

---

## 🚀 วิธีใช้งาน (Usage)

ใช้คำสั่ง `thpy` แทนคำสั่ง `python` ปกติ:

```bash
# รันสคริปต์ปกติ
thpy myscript.py

# ส่ง Arguments ไปยังสคริปต์
thpy myscript.py --port 8080 --env prod

# ดูความช่วยเหลือและเวอร์ชัน
thpy --help
thpy --version
```

### 💡 ทริกการใช้งานร่วมกับ Helix บน Termux
ในโปรแกรม **Helix** (`hx myscript.py`):
- กด `:` เพื่อเข้า Command Mode
- พิมพ์ `:sh thpy %` แล้วกด Enter เพื่อรันไฟล์ปัจจุบันและดูการ์ดภาษาไทยได้ทันที

---

## 🧪 การทดสอบ (Testing)

โปรเจกต์นี้ผ่านชุดทดสอบมาตรฐานและ Adversarial Stress Testing รวม 457 การทดสอบ:
```bash
python -m pytest tests/
```

---

## 📄 License
MIT License
