# Tycoon Empire — Roblox Game

สร้างอาณาจักรธุรกิจบน Roblox

## Project Structure

```
roblox-tycoon-empire/
├── ServerScriptService/
│   ├── LeaderstatsScript.lua    -- ระบบเงินผู้เล่น + Rebirth counter
│   ├── DataStoreScript.lua      -- Save/Load ข้อมูลผู้เล่น
│   └── RebirthScript.lua        -- ระบบ Rebirth + multiplier
├── Workspace/
│   └── TycoonPads/
│       ├── DropperScript.lua    -- สร้างทรัพยากร (drop items)
│       ├── ConveyorScript.lua   -- สายพานลำเลียง
│       ├── UpgraderScript.lua   -- เพิ่มมูลค่าสินค้า
│       ├── CollectorScript.lua  -- แปลงสินค้าเป็นเงิน
│       └── ButtonScript.lua     -- ปุ่มซื้อส่วนขยาย
├── StarterGui/                  -- UI (สร้างใน Roblox Studio)
└── ReplicatedStorage/           -- Shared assets & events
```

## How to Use

1. Open Roblox Studio
2. Copy each `.lua` file into the matching location in Explorer
3. Build the Tycoon Pad models (Dropper, Conveyor, Upgrader, Collector)
4. Set up Zones in Workspace per the GDD map layout
5. Test with 2-4 players

## Core Loop

เก็บทรัพยากร → ผลิตสินค้า → ขาย → อัปเกรด → ขยายธุรกิจ → แข่งขัน
