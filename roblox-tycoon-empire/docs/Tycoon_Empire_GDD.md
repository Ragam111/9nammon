# 🏭 Tycoon Empire

Game Design Document — สร้างเกมแนว Tycoon ใน Roblox ภายใน 24 ชม.

Roblox Studio Lua 24h Build

## ภาพรวมเกม

🎮

Concept

เกมแนว **Tycoon สร้างอาณาจักรธุรกิจ** บน Roblox — ผู้เล่นเริ่มต้นจากศูนย์ เรียนรู้เทคนิคพื้นฐาน (สร้าง, ขุด, ผลิต) ไต่ระดับขึ้นไปจนเปิดบริษัทของตัวเอง แข่งขันกับผู้เล่นอื่นในเซิร์ฟเวอร์เดียวกัน

🎯

Core Loop

**เก็บทรัพยากร → ผลิตสินค้า → ขาย → อัปเกรด → ขยายธุรกิจ → แข่งขัน**

- ทรัพยากร: ไม้, หิน, เหล็ก, ทอง, เพชร
- สินค้า: แปรรูปจากทรัพยากรดิบเพิ่มมูลค่า 2-10x
- เงิน: ใช้ซื้อที่ดิน, เครื่องจักร, จ้างพนักงาน NPC

👥

Target Player

- อายุ 9-18 ปี (Roblox core audience)
- ชอบเกม Tycoon, Simulator, Idle
- เล่นได้ทั้ง solo และ multiplayer

## ระบบเลื่อนขั้น 5 ระดับ

Tier 1 — Beginner

🪓 คนงานมือใหม่

- เรียนรู้การเคลื่อนที่, กระโดด, ใช้เครื่องมือ
- ขุดแร่ / ตัดไม้ด้วยมือ
- ขายทรัพยากรดิบที่ตลาดกลาง
- ปลดล็อก: สร้างเพิงพัก + เวิร์คเบ็นช์แรก

Tier 2 — Crafter

⚒️ ช่างฝีมือ

- แปรรูปทรัพยากรเป็นสินค้า (ไม้ → เฟอร์นิเจอร์)
- ตั้งแผงขายหน้าร้าน
- อัปเกรดเครื่องมือ (ไม้ → เหล็ก → ทอง)
- ปลดล็อก: ที่ดินแปลงแรก

Tier 3 — Factory Owner

🏭 เจ้าของโรงงาน

- สร้างโรงงานผลิตอัตโนมัติ (Conveyor Belt)
- จ้างพนักงาน NPC ช่วยขุด/ผลิต
- ซื้อเครื่องจักรเพิ่มประสิทธิภาพ
- ปลดล็อก: สายการผลิตหลายเส้น

Tier 4 — CEO

🏢 ผู้บริหารบริษัท

- สร้างออฟฟิศ + ตั้งชื่อบริษัท
- ระบบ R&D ปลดล็อกสินค้าพรีเมียม
- จ้าง Manager NPC ดูแลโรงงาน
- เทรดซื้อ-ขายกับผู้เล่นอื่น

Tier 5 — Tycoon

👑 จักรพรรดิธุรกิจ

- สร้างตึกสำนักงานใหญ่หลายชั้น
- แข่ง Leaderboard รายได้ต่อนาที
- ควบรวมกิจการ (ร่วมมือกับผู้เล่นอื่น)
- Event พิเศษ: ประมูลที่ดินทอง

## กลไกเกมหลัก

### 💰 ระบบเศรษฐกิจ

- **สกุลเงิน:** 💵 Cash (หาได้ในเกม) + 💎 Gems (พรีเมียม)
- **ราคาผันแปร:** ทรัพยากรมีราคาขึ้น-ลง ±20% ทุก 5 นาที
- **ภาษี:** บริษัทใหญ่จ่ายภาษี 5% ของรายได้ → เข้ากองกลางเซิร์ฟเวอร์
- **Money Sink:** ซ่อมเครื่องจักร, เงินเดือน NPC, อัปเกรด

### 🔧 ระบบ Conveyor / สายพาน

หัวใจของ Tycoon — ผู้เล่นวาง Dropper → Conveyor → Upgrader → Collector

- **Dropper:** สร้างทรัพยากรดิบทุก X วินาที
- **Conveyor Belt:** ลำเลียงจาก A → B
- **Upgrader:** เพิ่มมูลค่าสินค้า ×1.5 – ×3
- **Collector:** แปลงสินค้าเป็นเงิน

### 🏆 ระบบแข่งขัน

- **Leaderboard:** แสดง Top 10 รายได้สูงสุดในเซิร์ฟเวอร์
- **Company Wars:** ทุก 30 นาที จัดแข่งผลิตสินค้ามากที่สุด
- **Trade System:** ซื้อ-ขายทรัพยากรระหว่างผู้เล่น
- **Sabotage (ตัวเลือก):** ส่ง spy ชะลอโรงงานคู่แข่ง

### 🎒 ระบบ Rebirth

เมื่อเงินถึงเป้า สามารถ **Rebirth** เริ่มใหม่ แต่ได้ multiplier ถาวร

- Rebirth 1: ×1.5 รายได้
- Rebirth 2: ×2 รายได้ + สกิน Dropper ใหม่
- Rebirth 5: ×5 + ปลดล็อก VIP Zone

## แผนผังแมพ

แมพแบ่งเป็น 5 โซน วงกลม — ศูนย์กลางคือตลาด

```
    ┌─────────────────────────────────┐
    │         ⛰️ MINING ZONE          │
    │        (Tier 1-2 resources)     │
    │                                 │
    │  🌲 FOREST  ┌──────────┐  🏭   │
    │   ZONE      │  🏪 MARKET│ FACTORY│
    │  (ไม้,สมุนไพร) │  CENTER  │  ZONE │
    │             │ (ซื้อ-ขาย) │       │
    │             └──────────┘       │
    │                                 │
    │  🏢 COMPANY    🏠 STARTER      │
    │    DISTRICT      PLOTS          │
    │  (Tier 4-5)    (ที่ดินฟรี)      │
    │                                 │
    │         👑 VIP ZONE             │
    │      (Rebirth 5+ only)          │
    └─────────────────────────────────┘
      
```

### รายละเอียดแต่ละโซน

- **🏠 Starter Plots:** ที่ดิน 20×20 studs ฟรีสำหรับมือใหม่ มีเวิร์คเบ็นช์พื้นฐาน
- **🏪 Market Center:** NPC รับซื้อ-ขายทรัพยากร + กระดาน Leaderboard
- **⛰️ Mining Zone:** เหมืองหิน, เหล็ก, ทอง — ยิ่งลึกยิ่งมีค่า
- **🌲 Forest Zone:** ตัดไม้, เก็บสมุนไพร — ทรัพยากร respawn ทุก 30 วิ
- **🏭 Factory Zone:** ที่ดินใหญ่ 40×40 studs สำหรับสร้างโรงงาน (ซื้อด้วย Cash)
- **🏢 Company District:** ที่ดินพรีเมียม 60×60 + ออฟฟิศสำเร็จรูป
- **👑 VIP Zone:** Dropper พิเศษ, Upgrader ×10, ทรัพยากรเพชร

## แผนสร้างเกมภายใน 24 ชั่วโมง

MVP (Minimum Viable Product) — โฟกัส Tier 1-3 ก่อน เพิ่ม Tier 4-5 ทีหลัง

ชม. 0-2 — Setup

- ติดตั้ง Roblox Studio, สร้าง Baseplate ใหม่
- สร้าง Terrain พื้นฐาน (หญ้า, หิน, น้ำ)
- วาง Spawn Point + ตั้ง Lighting
- สร้าง Folder structure: Workspace > Zones, ServerScriptService > Scripts

ชม. 2-5 — Core Tycoon

- สร้าง Tycoon Pad (กดซื้อส่วนต่างๆ ของโรงงาน)
- เขียน Script ระบบ Dropper: สร้าง Part ตก + เพิ่ม Cash
- สร้าง Conveyor Belt (Part + BodyVelocity)
- สร้าง Collector: Touched → เพิ่มเงิน → ทำลาย Part

ชม. 5-8 — Economy

- ระบบ Leaderstats (เงินผู้เล่น)
- ปุ่มซื้อ Upgrader (เพิ่มมูลค่า Part)
- UI แสดงเงิน + ปุ่มซื้อของ (ScreenGui)
- ระบบ Save/Load ด้วย DataStore

ชม. 8-12 — Map Building

- สร้าง Market Center (NPC + ร้านค้า)
- สร้าง Mining Zone (หิน clickable, respawn)
- สร้าง Starter Plots × 8-12 (แต่ละคนมีพื้นที่ของตัวเอง)
- ใส่ Toolbox models ตกแต่ง (ต้นไม้, อาคาร)

ชม. 12-16 — Upgrade Path

- ระบบซื้อ Dropper ระดับ 2, 3 (รายได้สูงขึ้น)
- ระบบ Rebirth (เริ่มใหม่ + multiplier)
- Leaderboard UI (SurfaceGui บนป้ายกลางแมพ)
- เสียง SFX: เก็บเงิน, ซื้อของ, Level Up

ชม. 16-20 — Polish

- Particle effects (เงินกระเด็น, ควันโรงงาน)
- ป้ายชื่อบริษัท (BillboardGui เหนือหัวผู้เล่น)
- Tutorial NPC ที่ Spawn สอนพื้นฐาน
- Game Icon + Thumbnail

ชม. 20-24 — Test & Publish

- ทดสอบ 2-4 players ในเซิร์ฟเวอร์
- แก้ Bug ระบบ DataStore / Economy
- ตั้ง Max Players, Genre, Thumbnail
- กด **Publish to Roblox** 🎉

## โค้ดตัวอย่าง (Lua)

วางใน ServerScriptService — คัดลอกไปใช้ใน Roblox Studio ได้เลย

### 1. Leaderstats (เงินผู้เล่น)

```
-- ServerScriptService > LeaderstatsScript
game.Players.PlayerAdded:Connect(function(player)
    local leaderstats = Instance.new("Folder")
    leaderstats.Name = "leaderstats"
    leaderstats.Parent = player

    local cash = Instance.new("IntValue")
    cash.Name = "Cash"
    cash.Value = 100  -- เงินเริ่มต้น
    cash.Parent = leaderstats
end)
```

### 2. Dropper (สร้างทรัพยากร)

```
-- Script ใน Dropper Part
local dropper = script.Parent
local dropPart = dropper:FindFirstChild("DropPart")

while true do
    wait(2)  -- ดรอปทุก 2 วินาที
    local item = Instance.new("Part")
    item.Size = Vector3.new(1, 1, 1)
    item.BrickColor = BrickColor.new("Gold")
    item.Position = dropPart.Position
            - Vector3.new(0, 2, 0)
    item.Parent = workspace

    -- เพิ่ม value ให้ Part
    local val = Instance.new("IntValue")
    val.Name = "Value"
    val.Value = 5
    val.Parent = item

    -- ลบหลัง 15 วินาที
    game.Debris:AddItem(item, 15)
end
```

### 3. Collector (แปลงเป็นเงิน)

```
-- Script ใน Collector Part
local collector = script.Parent
-- ownerValue คือ StringValue เก็บชื่อเจ้าของ
local ownerValue = collector:FindFirstChild("Owner")

collector.Touched:Connect(function(hit)
    local val = hit:FindFirstChild("Value")
    if val then
        local ownerName = ownerValue.Value
        local player = game.Players:FindFirstChild(
            ownerName
        )
        if player then
            player.leaderstats.Cash.Value =
                player.leaderstats.Cash.Value
                + val.Value
        end
        hit:Destroy()
    end
end)
```

### 4. Tycoon Button (ซื้อส่วนขยาย)

```
-- Script ใน Button Part (ปุ่มกดบนพื้น)
local button = script.Parent
local price = button:FindFirstChild("Price").Value
local itemToUnlock = button:FindFirstChild("ItemName").Value
local debounce = false

button.Touched:Connect(function(hit)
    if debounce then return end
    local player = game.Players:GetPlayerFromCharacter(
        hit.Parent
    )
    if not player then return end
    if player.leaderstats.Cash.Value >= price then
        debounce = true
        player.leaderstats.Cash.Value =
            player.leaderstats.Cash.Value - price
        -- ปลดล็อกโมเดล
        local model = workspace.HiddenItems
            :FindFirstChild(itemToUnlock)
        if model then
            model.Transparency = 0
            model.CanCollide = true
        end
        button:Destroy()
    end
end)
```

### 5. DataStore (เซฟข้อมูล)

```
-- ServerScriptService > DataStoreScript
local DSS = game:GetService("DataStoreService")
local store = DSS:GetDataStore("PlayerData_v1")

game.Players.PlayerAdded:Connect(function(player)
    local key = "Player_" .. player.UserId
    local success, data = pcall(function()
        return store:GetAsync(key)
    end)
    if success and data then
        player.leaderstats.Cash.Value = data.Cash or 0
    end
end)

game.Players.PlayerRemoving:Connect(function(player)
    local key = "Player_" .. player.UserId
    pcall(function()
        store:SetAsync(key, {
            Cash = player.leaderstats.Cash.Value
        })
    end)
end)
```

## ลิงก์เรียนรู้ Roblox Studio

เปิดเรียนตามลำดับ — เริ่มจาก Studio พื้นฐาน แล้วค่อยไป Lua Scripting

### 📘 เริ่มต้น Roblox Studio

[🏫 Roblox Creator Hub — Studio Curriculum หลักสูตรอย่างเป็นทางการจาก Roblox เรียนฟรี](https://create.roblox.com/docs/tutorials/curriculums/studio) [📖 Roblox Documentation เอกสารอ้างอิง API ทั้งหมด — ค้นหาฟังก์ชันทุกตัว](https://create.roblox.com/docs) [🎓 Roblox Studio for Beginners — Step by Step สอนตั้งแต่ดาวน์โหลดจนสร้างเกมแรก](https://www.rts.school/en/blog/roblox-studio-for-beginners)

### 💻 Lua Scripting

[📝 Luau Programming Language เอกสาร Luau (Lua ของ Roblox) อย่างเป็นทางการ](https://create.roblox.com/docs/luau) [🎮 Lua Scripting in Roblox — Complete Guide GameDev Academy สอน Lua ตั้งแต่พื้นฐาน](https://gamedevacademy.org/lua-scripting-in-roblox-tutorial-complete-guide/)

### 🏭 Tycoon เฉพาะทาง

[🎬 Udemy — Build a Complete Tycoon with Lua 2026 คอร์สเต็มรูปแบบ สร้าง Tycoon จากศูนย์](https://www.udemy.com/course/roblox-studio-mastery-build-a-complete-tycoon-with-lua-2026/) [🛠 How to Build a Game in Roblox Studio สอน workflow สร้างเกมครบจบในบทเดียว](https://www.obby.fun/blog/how-to-build-game-roblox-studio)

### 📥 ดาวน์โหลด

[⬇️ ดาวน์โหลด Roblox Studio create.roblox.com — ฟรี, ใช้ได้ทั้ง Windows และ Mac](https://create.roblox.com/landing)