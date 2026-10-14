#!/usr/bin/env bash
# install.sh — ตัวติดตั้ง Local Code Assistant บน Linux / macOS
# รันด้วย: bash install.sh  (หรือ chmod +x install.sh && ./install.sh)
#
# ทำงานคู่กับ install.ps1 (เวอร์ชัน Windows) — logic เลือกโมเดลตาม RAM เหมือนกัน
set -euo pipefail

INSTALL_DIR="${LCA_INSTALL_DIR:-$HOME/.local-code-assistant}"
# ตั้งค่าตำแหน่งติดตั้งเองได้ผ่าน env var เช่น:
#   LCA_INSTALL_DIR=/mnt/external-drive/lca bash install.sh
# (เทียบเท่ากับตัวเลือกไดรฟ์ D: ในเวอร์ชัน Windows — Linux/macOS ไม่มี drive letter
# แต่ mount point อื่นทำหน้าที่เดียวกันได้)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="0.0.2"

BOLD='\033[1m'; CYAN='\033[96m'; GREEN='\033[92m'; YELLOW='\033[93m'; RED='\033[91m'; RESET='\033[0m'

echo -e "${CYAN}${BOLD}=== Local Code Assistant — ตัวติดตั้ง (Linux/macOS) ===${RESET}"

# ---------- ขั้นตอน 1: ตรวจสอบ Python ----------
PYTHON_CMD=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_CMD="$candidate"
        break
    fi
done
if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}[error] ไม่พบ Python 3 ในเครื่อง${RESET}"
    echo "        macOS: brew install python3"
    echo "        Ubuntu/Debian: sudo apt install python3"
    exit 1
fi
echo "[ok] พบ Python: $PYTHON_CMD ($($PYTHON_CMD --version))"

# ---------- ขั้นตอน 2: ตรวจสอบ Ollama ----------
HAS_OLLAMA=0
if command -v ollama >/dev/null 2>&1; then
    HAS_OLLAMA=1
    echo "[ok] พบ Ollama"
else
    echo -e "${YELLOW}[warn] ไม่พบ Ollama — ติดตั้งด้วย: curl -fsSL https://ollama.com/install.sh | sh${RESET}"
    echo "       (macOS ก็ใช้คำสั่งเดียวกันนี้ได้ หรือโหลดแอปจาก https://ollama.com/download/mac)"
fi

# ---------- ขั้นตอน 3: ตรวจ RAM แล้วเลือกโมเดลที่แนะนำ ----------
# หา RAM รวมเป็น GB — วิธีต่างกันระหว่าง Linux (/proc/meminfo) กับ macOS (sysctl)
if [ "$(uname)" = "Darwin" ]; then
    TOTAL_RAM_BYTES=$(sysctl -n hw.memsize)
    TOTAL_RAM_GB=$(( TOTAL_RAM_BYTES / 1024 / 1024 / 1024 ))
else
    TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    TOTAL_RAM_GB=$(( TOTAL_RAM_KB / 1024 / 1024 ))
fi

if   [ "$TOTAL_RAM_GB" -lt 8 ];  then MODEL="qwen2.5-coder:0.5b"; TIER="ต่ำกว่า 8GB (อาจยังหน่วง)"
elif [ "$TOTAL_RAM_GB" -lt 16 ]; then MODEL="qwen2.5-coder:1.5b"; TIER="8GB"
elif [ "$TOTAL_RAM_GB" -lt 32 ]; then MODEL="qwen2.5-coder:7b";   TIER="16GB"
elif [ "$TOTAL_RAM_GB" -lt 64 ]; then MODEL="qwen2.5-coder:14b";  TIER="32GB"
else                                   MODEL="qwen2.5-coder:32b";  TIER="64GB ขึ้นไป"
fi

echo ""
echo "[ram] เครื่องนี้มี RAM ประมาณ ${TOTAL_RAM_GB}GB (ระดับ: $TIER)"
echo -e "${GREEN}[ram] โมเดลที่แนะนำ: $MODEL${RESET}"
read -rp "กด Enter เพื่อใช้โมเดลที่แนะนำ หรือพิมพ์ชื่อโมเดล Ollama อื่นที่ต้องการ: " MODEL_CHOICE
MODEL_CHOICE="${MODEL_CHOICE:-$MODEL}"

# ---------- ขั้นตอน 4: คัดลอกไฟล์ไปที่โฟลเดอร์ติดตั้ง ----------
if [ -d "$INSTALL_DIR" ]; then
    echo "[info] พบการติดตั้งเดิมที่ $INSTALL_DIR — ไฟล์ผู้ใช้ (todos.json, CHANGELOG_local.md) จะไม่ถูกลบ"
else
    mkdir -p "$INSTALL_DIR"
fi

cp "$SCRIPT_DIR/local_coder.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/server.py" "$INSTALL_DIR/"
mkdir -p "$INSTALL_DIR/app"
cp "$SCRIPT_DIR"/app/*.py "$INSTALL_DIR/app/"
cp "$SCRIPT_DIR"/app/*.html "$INSTALL_DIR/app/"

# folder_trust.py / context_manager.py อยู่ที่ root ของแพ็กเกจ (ไม่ใช่ใน app/)
# แต่ local_coder.py import ผ่าน sys.path ที่ชี้ไปโฟลเดอร์ app/ ตอนรัน
# ต้องคัดลอกมาไว้ที่นี่ด้วยเสมอ ไม่งั้นจะเจอ ModuleNotFoundError ตอนเปิดโปรแกรม
cp "$SCRIPT_DIR/folder_trust.py" "$INSTALL_DIR/app/"
cp "$SCRIPT_DIR/context_manager.py" "$INSTALL_DIR/app/"

echo "$VERSION" > "$INSTALL_DIR/version.txt"
echo "$MODEL_CHOICE" > "$INSTALL_DIR/default_model.txt"
echo "[ok] ติดตั้งไฟล์ไปที่ $INSTALL_DIR แล้ว"

# ---------- ขั้นตอน 5: สร้าง launcher ----------
cat > "$INSTALL_DIR/lca" <<EOF
#!/usr/bin/env bash
# lca — เรียกใช้ Local Code Assistant จากที่ไหนก็ได้ใน terminal
exec "$PYTHON_CMD" "$INSTALL_DIR/local_coder.py" --model "$MODEL_CHOICE" "\$@"
EOF
chmod +x "$INSTALL_DIR/lca"

cat > "$INSTALL_DIR/lca-web" <<EOF
#!/usr/bin/env bash
# lca-web — เปิดหน้าเว็บ Chat UI (ต้องระบุโฟลเดอร์โปรเจกต์เป็น argument แรก)
exec "$PYTHON_CMD" "$INSTALL_DIR/server.py" "\$@"
EOF
chmod +x "$INSTALL_DIR/lca-web"

echo "[ok] สร้าง launcher แล้ว: lca (CLI), lca-web (หน้าเว็บ)"

# ---------- ขั้นตอน 6: เพิ่ม INSTALL_DIR เข้า PATH (ถ้ายังไม่มี) ----------
SHELL_RC=""
case "$SHELL" in
    */zsh)  SHELL_RC="$HOME/.zshrc" ;;
    */bash) SHELL_RC="$HOME/.bashrc" ;;
    *)      SHELL_RC="$HOME/.profile" ;;
esac

if ! grep -q "$INSTALL_DIR" "$SHELL_RC" 2>/dev/null; then
    echo "export PATH=\"\$PATH:$INSTALL_DIR\"" >> "$SHELL_RC"
    echo "[ok] เพิ่ม $INSTALL_DIR เข้า PATH ใน $SHELL_RC แล้ว — รัน 'source $SHELL_RC' หรือเปิด terminal ใหม่"
else
    echo "[ok] $INSTALL_DIR อยู่ใน PATH ($SHELL_RC) อยู่แล้ว"
fi

# ---------- สรุป ----------
echo ""
echo -e "${CYAN}${BOLD}=== ติดตั้งเสร็จสมบูรณ์ ===${RESET}"
echo "1. รัน: source $SHELL_RC   (หรือเปิด terminal ใหม่)"
if [ "$HAS_OLLAMA" = "1" ]; then
    echo "2. ดึงโมเดล: ollama pull $MODEL_CHOICE"
else
    echo "2. ติดตั้ง Ollama ก่อน แล้วรัน: ollama pull $MODEL_CHOICE"
fi
echo "3. ใช้งาน: lca /path/to/your/project"
echo "   หรือเปิดหน้าเว็บ: lca-web /path/to/your/project"
